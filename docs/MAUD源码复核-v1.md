# MAUD 源码复核与借鉴清单 v1

日期：2026-11-05
复核对象：本机 `C:\MAUD2` / `C:\MAUD3` 安装（`lib/Maud.jar`，2931 个类，JDK 21 构建）+
上游源码 [github.com/luttero/maud](https://github.com/luttero/maud) `version3` 分支
（v3.09，2026-11-04 提交 728f977）。
关联文档：[`docs/评估报告-实样对拍-MAUD-v1.md`](评估报告-实样对拍-MAUD-v1.md)（实证侧）。

## 0. 结论摘要

1. **引擎层面 MAUD 没有可借鉴的优势。** 它的 Marquardt 实现是
   1990 年代风格的「全内存 Jacobian + 前向差分导数 + Cholesky」，
   算法内部**不处理参数边界**（由 Parameter 层在别处管），也没有
   自动收敛判据。我们的变量投影（scale/背景解析求解）+ 逐参数边界 +
   ΔRwp 收敛判据在数值结构上更稳。
2. **值得借鉴 6 项**，按预期收益排序见 §4 表格。前三项（插值背景、
   权重模式、Brindley 微吸收）是我们目前**完全没有**的能力，
   且都能直接对应到本次实样对拍的失配证据。
3. **源码复核修正/印证了两个对拍判断**（§3）：
   - MAUD 的低角背景优势来自「Chebyshev 多项式 **+ 10 次插值背景迭代**
     （默认，间隔 150 点）」的**两层可加结构**——不是单纯的多项式阶数；
   - 用户 `.par` 里 5 次迭代就停确实只是配置：MAUD 引擎本身支持
     深度收敛（λ > 10⁵·λ_min 才判停），「Rwp 是中途值」的判断成立。

## 1. 复核方法与范围

| 途径 | 内容 |
|---|---|
| 本机 `Maud.jar` 解包 | 2931 类的完整类清单（`it.unitn.ing.rista.*` 727 类），交叉定位源码文件 |
| 上游源码（WebFetch 拉取 raw 文件） | `comp/MarqardLeastSquares.java`、`diffr/Background.java`、`diffr/DiffrDataFile.java`、`diffr/DataFileSet.java`、`diffr/Sample.java`、`diffr/Layer.java`、`diffr/Phase.java`、`diffr/FilePar.java`、`diffr/rta/WIMVTexture.java`、`diffr/sizestrain/SizeStrainPopa.java` |
| 未逐行复核 | GUI 层（awt 包）、XRF/反射率/多层膜、`Uwimvuo`（WIMV 核心 Fortran 移植，仅确认接口） |

网络说明：GitHub 直连被重置，git clone（含 3 个镜像）均失败；
`api.github.com` 与 `raw.githubusercontent.com` 经 WebFetch 通道可读，
`DiffrDataFile.java` / `DataFileSet.java` 等超大文件被截断，
相关结论以「可见代码 + 偏好默认值」为准，已标注。

## 2. 源码事实（逐模块）

### 2.1 Marquardt 引擎（`comp/MarqardLeastSquares.java`）

```java
double lambda = 0.01;            // 初始阻尼
lambda *= 0.31622777;            // 每轮外迭代 λ ← λ/√10
...
lambda *= 10.0;                  // 步被拒 / Cholesky 失败 → λ ×10
if (lambda > 100000.0 * lmin) conver = 1;   // 深度收敛判停
...
if (Math.abs(g[i]) <= Math.abs(prcsn * s_deriv[i]))  ++n0;  // prcsn=1e-8
...
double derstep = 0.001;          // 前向差分：step = 0.001·|p|（p=0 时取 0.001）
```

- 导数：**前向有限差分**，每参数一次完整前向计算（无解析导数）；
- 线性代数：对称矩阵打包 + **Cholesky** 分解回代（负对角即失败 → 加大 λ）;
- **算法内部无参数边界**：`getfreeParameters()` 把 lbound/ubound 一并传入
  （`FilePar.java`），但 MarqardLeastSquares 从不使用它们；
- 终止：迭代数到上限 / 全部 |Δp| ≤ 10⁻⁸·|p| / λ > 10⁵·λ_min / WSS < wssLimit；
- 无自动重启、无参数分组调度。多优化器（Simplex/GA/SA/混合蒙特卡洛/
  最大熵）通过 `OptimizationAlgorithm` 插拔，与我们 backend 类似但更全。

**对照**：我们的 LM（`core/refine/lm.py`）+ 变量投影在每次迭代内解析求出
scale/背景，自由维数远小于 MAUD 的全参数向量；且我们有逐参数边界
（`_bounds`）。**没有要抄的东西。**

### 2.2 背景模型（`diffr/Background.java` + `DiffrDataFile.java` + `DataFileSet.java`）

MAUD 的总背景是**三层可加**（`DiffrDataFile.getBkgFit`，逐字引用）：

```java
protected double[] bkgfit = null;      // 多项式/Chebyshev 参数算出来的
protected double[] intbkgfit = null;   // 插值背景
protected double[] expbkgfit = null;   // 实验背景（另一 datafile 或手工）
public double getBkgFit(int index) {
    return finalIntensityCalibration(bkgfit[index]) + intbkgfit[index] + expbkgfit[index];
}
```

- 多项式层：`_riet_par_background_pol` 系数序列 + `_riet_chebyshev_polynomial_background`
  开关（Chebyshev 是**可选**，不是默认全部）；
- 插值层（这次实样差距的真正来源）：偏好默认值在 `DataFileSet`：

```java
setInterpolatedPoints(MaudPreferences.getInteger(
    "backgroundSubtraction.interpolatedPointsInterval", 150));
setBackgroundInterpolationIterations(MaudPreferences.getInteger(
    "backgroundSubtraction.iterations", 10));
```

  即**默认 10 次迭代、每 150 点一个插值段**——对 5–120°（~7000 点）等效
  约 47 个控制点，与我们 tent20 同量级但**分布在数据点网格上**、且随迭代
  自适应下压，不需要用户调节点数；
- 手工背景点：`_riet_background_interpolated_point_position`（图上点选）；
- 还可以把另一个 datafile 直接当背景、以及 `Oscillator` 振荡分量。

**对照**：我们只有单层 `cheb`/`tent` 基（`core/background.py`），
没有「随迭代自适应下压」的机制，也没有手动背景点。

### 2.3 数据点权重（`DiffrDataFile.getWeight`）

```java
switch (weightSwitch) {
    case 0: value = weight[index];            break;  // 文件自带 σ（_pd_meas_intensity_sigma）
    case 1: value = 1.0 / Math.sqrt(yint);    break;  // 计数统计
    case 2: value = 1.0 / yint;               break;
    case 3: value = 1.0;                      break;  // 常数权重
}
```

另有 `theoreticalWeights` 模式（用**计算值**代替观测值定权，抗弱峰噪声
漂移）和可选 q^qExp 加权。排除区间权重置 0。

**对照**：我们固定 `σ = √max(I,1)`（`solve()`/`refine_cell_full` 一致），
对「计数型原始数据」正确；但没有可选模式，也没有用文件自带 σ 的路径。

### 2.4 织构（`diffr/rta/WIMVTexture.java` + `Uwimvuo`）

- ODF 是**离散三维网格**（非谐波展开），默认分辨率 **5°**；
- 每个极图用三角插值 + Simpson 积分；负 ODF 值直接截断；
- WIMV 迭代默认：**ITZ=20 次**、迭代指数 R=2.0、zigzag 模式 RFAK=1.1、
  停止阈值 Rp=1.0%；
- **重叠反射按强度权重平均**进入织构因子（`getPoleIntensity`）；
- 结果：**每条反射一个织构因子**——这是样品 3（CaF₂ 111）我们用单参数
  March–Dollase 只能部分弥补的差距。

**对照**：我们每相一个 March–Dollase (hkl, r)。v1.2 的 ODF 计划与该实现
对齐（离散网格 + 迭代正交化比谐波展开更容易做到「每反射一因子」）。

### 2.5 尺寸/应变各向异性（`diffr/sizestrain/SizeStrainPopa.java`）

```java
public double getBetaChauchy(double dspace, double cryst, double mstrain) {
    return 2.0 / 3.0 * dspace * dspace / Math.abs(cryst);   // 尺寸项（Cauchy 积分宽）
}
public double getBetaGauss(double dspace, double cryst, double mstrain) {
    return 2.0 * Math.abs(mstrain) * Constants.mstraintoetilde * dspace;  // 应变项（Gauss）
}
```

Popa LB = 按反射方向 (hkl) 的 d 值谐函数展开调制上两个基本项
（各向异性部分在 `SizeStrainSymPopa`）。注意样品 5 出现的
「Popa 参数 −302」在我们对拍里是 MAUD 的不可辨识参数——
**能力有价值，但需要像我们一样给强先验/边界**。

### 2.6 QPA 与微吸收（`Layer.java` / `Phase.java` / `Sample.java`）

- 重量分数：`W_i = V_i·ρ_i / Σ V_j·ρ_j`（`getWeightedPhaseQuantity`），
  ρ = Z·M/(N_A·V)。数学上与 Hill–Howard `W_i ∝ S_i(ZMV)_i` 同族
  （scale→体积分数的换算吸收了 V²），**我们的 QPA 无需改动**；
- **微吸收（Brindley）**：`MicroAbsorptionBrindley` 模型，因子
  `Muf = (1 − exp(−m·r))/(m·r)`（m=线吸收系数，r=晶粒尺寸；
  源码里保留了 Rietquan 2.3 的 Basic 参考注释），经
  `Phase.getApparentQuantity(...)` 作用于每相强度；
  晶粒尺寸参数就是 `_exptl_absorpt_cryst_size`。
  **我们没有这个能力**——实样含针铁矿/萤石等高 μ 相时 QPA 会系统性偏。

### 2.7 精修调度（`diffr/FilePar.java`）

- 自由参数 = 全局 `isRefinable()` 过滤，**没有**按迭代阶段自动分组调度；
- **没有**自动收敛/自动停止/触界自动移界（可见代码层面）；
- 停止靠用户手点（"Are you sure to stop the running computation?"）。

**对照**：我们的 `RecipeRunner`（8 步配方 + 快照回退 + ΔRwp<tol）在
「自动化」上领先；MAUD 用户要靠经验多次点 calculate——这也解释了
为什么本次 7 个 `.par` 全部停在 5 次迭代。

## 3. 对拍结论的源码印证

| 对拍判断 | 源码证据 | 结论 |
|---|---|---|
| 「MAUD 的 Rwp 是中途值，5 次迭代没到平台」 | 引擎收敛条件是 λ>10⁵·λ_min 级深收敛，迭代数由用户给（本次全为 5） | ✅ 成立 |
| 「背景差距 ≈ tent20 vs cheb3」 | MAUD 默认 Chebyshev + **10 次插值迭代 × 150 点间隔**，两层可加；等效自由度 ≈ 40–50 | ✅ 成立，且方向（加密、自适应）比「提高多项式阶数」更对 |
| 「每反射一个织构因子，我们单 MD 不够」 | WIMV 离散 ODF → 每反射因子，重叠反射加权平均 | ✅ 成立 |
| 「坐标/B 因子吸收强度失配」 | MAUD 原子坐标/B/占位全部可精修（含各向异性 B），无约束时确实会把失配吃进结构 | ✅ 成立（无防呆） |
| 微吸收会造成 QPA 偏差（新发现） | Brindley 因子按相作用于强度 | ⚠️ 对拍时未建模，属我们的**新缺口** |

## 4. 可借鉴清单（按收益/成本排序）

| # | MAUD 能力 | 建议落点 | 预期收益 | 成本 |
|---|---|---|---|---|
| **1** | 插值背景迭代（默认 10 次 ×150 点）+ 手动背景点 | `core/background.py`：`tent` 基加「低角加密 + 逐轮下压」选项；GUI 图上点选背景点 → `manual` 模式已有骨架 | 实测同族能力差 2–9 点/样；P1 已验证方向 | 中 |
| **2** | Brindley 微吸收 `(1−e^(−μr))/μr` 按相校正 | 相级可选参数 `microabs_mu_r`；进 `compute_phase_profile` 强度链 | 高 μ 实样（Fe 相/萤石）QPA 系统偏差 | 中 |
| **3** | 权重模式 4 选 + theoreticalWeights | `RefineConfig.weight_mode`（"sigma_file"/"sqrt"/"1/y"/"const"/"theoretical"） | 低信噪比/弱峰样品的稳健性 | 低 |
| **4** | EWIMV 离散 ODF（每反射一因子） | v1.2 织构模块（已规划）；重叠反射加权平均细节照抄语义 | 样品 3 实测 −12 点量级 | 高 |
| **5** | Popa LB 各向异性尺寸/应变 | `SizeStrainSymPopa` 语义；**必须**带边界与可辨识性检查（MAUD 自身翻车案例 −302） | 样品 5/6 峰宽矛盾 | 高 |
| **6** | 多优化器插拔（Simplex/GA/SA） | `RecipeRunner` 已可挂第二引擎；仅作病态问题后手 | 锦上添花 | 低优先 |

## 5. 明确不建议借鉴

| 项 | 理由 |
|---|---|
| Marquardt 数值细节（λ=0.01/√10 折返、前向差分 0.1%、Cholesky 全内存） | 我们变量投影 + 解析线性层自由度更少、且有边界；全内存 Jacobian（dataNumber×nprm）在大点数下更耗内存 |
| QPA 换算公式 | 与 Hill–Howard 数学等价，改了只会引入回归风险 |
| 无自动收敛判据 | 我们 ΔRwp<tol + 快照回退更工程化 |
| 把晶粒尺寸参数同时用于微吸收与动力学效应（`_exptl_absorpt_cryst_size` 双义） | MAUD 自己的参数语义混乱点，不学 |

## 6. 复现方式

```bash
# 本机类清单（定位源码文件用）
unzip -l C:/MAUD3/lib/Maud.jar | awk '{print $4}' | grep '\.class$' > C:/Temp/maud_classes.txt
# 源码（GitHub 直连失败时走 WebFetch 读 raw 文件；镜像 gitclone.com 不可用）
# https://raw.githubusercontent.com/luttero/maud/version3/src/it/unitn/ing/rista/...
```

本文引用的源码片段均来自 `version3` 分支 v3.09（2026-11-04），
与本机 `Maud.jar`（JDK 21 构建）的类清单交叉核对一致；
用户 `.par` 来自 MAUD 2.99993（C:\MAUD2），引擎层与本复核结论一致
（两个版本的 Marquardt/背景框架同源）。
