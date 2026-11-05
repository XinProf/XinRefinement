# vendored from PolyXRD-RutAna :: rutana/core/refine/nonlinear.py
"""B 法精修 · 非线性层（T4.4，核心：变量投影 separable NLS）。

技术决策 D3：scale 与背景系数是线性参数，每次迭代内用 lstsq 解析求解；
LM 只迭代非线性参数，待优化参数从 ~15 降到 ~5。

v1.0.0 扩展（真实数据调优成果，见 docs/VALIDATION_v1.0.0.md）：
- 背景模式 bg_mode="cheb"|"tent"（tent = 分片线性帽，真实大弯背景更优）
- refine_asym / refine_bfactor：低角不对称尾 + 经验高角衰减
- refine_cell：每相晶胞 a,c 缩放（±1%，T4.7 内容）
- progress_cb(msg, pct) / on_iter(gen, rwp)：GUI 忙窗回调（默认 None）

v1.4.0 扩展（择优取向精修，见 docs/VALIDATION_v1.0.0.md §v1.4.0 实证）：
- refine_po：March–Dollase 择优取向参数 r 精修（每相一个 r，边界
  PO_BOUNDS=(0.2, 5.0)；缺相按 DEFAULT_PO_HKL 补 (h,k,l,1.0) 起点）。
  峰强经 forward 的明细路径前向施加（缓存键不含 r，每次评估 O(峰数)），
  单样本耗时不劣化超过关闭版的 ~1.x 倍。

residual_fn(x):
  x -> 重建 ProfileParams(+每相晶胞) -> compute_phase_profile 各相
  -> solve_linear 解析出 scale+背景 -> 返回加权残差 (y_obs − y_calc)/σ。
history 记录每次残差评估的 Rwp（含被拒绝的试探，画收敛曲线用）。

NCA 修改（T6.3a）：可取消的精修。
- 新增 `RefineCancelled` 异常与 `RefineConfig.cancel_cb`（callable() -> bool）。
- 为什么不能靠 `progress_cb` / `on_iter` 取消：这两处调用都被
  `try/except Exception: pass` 包着（vendor 的既定行为 —— 回调异常不许
  影响精修），回调里抛异常出不来。而 GUI 必须能取消一次跑了 200 s 的
  精修（T1.4 实测病态结构 >200 s）。
- 取消检查放在**残差函数入口**：LM 每次迭代要评估 n+1 次残差，scipy trf
  后端同理，故这里是响应最快、且两个后端都覆盖的位置。
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field, replace

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import (
    ANISO_DIAG_IDX,
    ANISO_SIZE_BOUNDS,
    ANISO_SIZE_CROSS,
    ANISO_STRAIN_BOUNDS,
    ANISO_STRAIN_CROSS,
    MIN_W,
    TEXTURE_BOUNDS,
    TEXTURE_N_GRID,
    ProfileParams,
    compute_phase_profile,
    normalize_texture_grid,
)
from xinrefinement.core.refine.optimizers import minimize as _optimize
from xinrefinement.core.refine.linear import solve_linear_detail
from xinrefinement.core.refine.rfactors import RFactors, compute_rfactors
from xinrefinement.core.params.registry import (
    ParameterRegistry,
    build_registry_from_config,
)

# 参数边界（TASKS T4.4 冻结值 + v1.0.0 扩展）
ZERO_BOUNDS = (-0.5, 0.5)
UVW_BOUNDS = (0.0, 5.0)
V_BOUNDS = (-0.5, 0.5)              # v1.0.0: 真实数据 Caglioti V 可为负（实测 -0.04）
ETA_BOUNDS = (0.05, 1.0)
ASYM_BOUNDS = (-0.05, 0.30)
BFACTOR_BOUNDS = (0.0, 6.0)
CELL_BOUNDS = (0.99, 1.01)          # 晶胞 a,c 缩放 ±1%
# v1.4.0: March–Dollase 择优取向参数 r 边界（r=1 为无择优）
PO_BOUNDS = (0.2, 5.0)
# v1.3: Brindley 微吸收 mu*r 边界（下限避开 0 的奇点，20 对应近全吸收）
MICROABS_BOUNDS = (0.01, 20.0)
# v1.3 任务 #14: 织构光滑罚默认权重（边界见 forward.TEXTURE_BOUNDS）
TEXTURE_LAMBDA = 1.0
#: v1.3 任务 #15：Popa LB 各向异性 12 参数的边界（size 6 + strain 6）
ANISO_BOUNDS = (ANISO_SIZE_BOUNDS, ANISO_STRAIN_BOUNDS)
#: 开各向异性所需的最少独立晶向数（12 参数的可辨识性护栏）
ANISO_MIN_DIRS = 8
#: 织构网格末端节点（χ=90°，远离织构轴）锚定到 1.0 的权重。
#: 物理依据：纤维织构的「远场」回归无织构；数学上它同时消除
#: 「T 整体乘常数 ↔ 该相 scale 除常数」这条零空间（否则 T 水平不可辨识）。
TEXTURE_ANCHOR_W = 100.0
# NCA 修改（T2.1）: TCH 洛伦兹项边界。X = 4ε（度），Y = Kλ/D（度）。
# Y 上限 0.5° 对应 D ≈ 0.16 nm（纳米晶下限）；X 上限 0.5° 对应 ε ≈ 2.2e-3。
SIZE_BOUNDS = (0.0, 0.5)     # Y
STRAIN_BOUNDS = (0.0, 0.5)   # X
# v1.4.0: 已知惯习面的内置相择优取向默认 (h,k,l)（TiO2 惯习：锐钛板状
# (001)、金红石柱状 (110)）；未知相名不纳入 PO 精修。
DEFAULT_PO_HKL = {"anatase": (0, 0, 1), "rutile": (1, 1, 0)}


class RefineCancelled(Exception):
    """精修被用户取消（T6.3a）。

    GUI 的「取消」按钮置位 `cancel_cb` 后，核心层在下一次残差评估时抛出本异常，
    由 `refine()` 一路透传给调用方（不被任何 except 吞掉）。
    """


@dataclass(frozen=True)
class RefineConfig:
    """精修开关与数值配置。"""

    refine_zero: bool = True
    refine_uvw: bool = True
    refine_eta: bool = False
    n_bg: int = 3
    max_iter: int = 40
    sigma: np.ndarray | None = None
    tmin: float = 5.0
    tmax: float = 90.0
    # ---- v1.0.0 扩展（默认关闭，保持 v0.1.0 行为） ----
    bg_mode: str = "cheb"            # "cheb" | "tent" | "interp"（v1.2.0）
    refine_asym: bool = False        # 低角不对称尾
    refine_bfactor: bool = False     # 经验高角衰减 B
    refine_cell: bool = False        # 每相晶胞 a,c 缩放 (T4.7)
    #: v1.3 #16：优化器插拔——"lm"（自研，默认）| "trf" | "dogbox" |
    #: 历史别名 "scipy"（= trf）。见 core.refine.optimizers.OPTIMIZERS。
    backend: str = "lm"
    progress_cb: object = None       # callable(msg: str, pct: float | None)
    on_iter: object = None           # callable(gen: int, rwp: float)
    # ---- v1.2.0 扩展：定权模式（对照 MAUD DiffrDataFile.getWeight） ----
    #: "sqrt"（默认，1/σ∝1/√y 计数统计，与 v1.1.x 逐位一致）| "file"
    #: （谱图 meta["sigma"]，缺则回退 sqrt）| "unit"（常数权）| "1/y"
    #: | "theoretical"（v1.3：σ=√max(ycalc,1)，MAUD theoreticalWeights，
    #:   抗弱峰噪声漂移；solve() 入口解析为固定 σ 数组）
    weight_mode: str = "sqrt"
    # ---- v1.2.0 扩展：手动/插值背景（固定曲线，MAUD 两层可加语义） ----
    #: bg_mode="manual" 时的锚点序列 ((2θ, I), ...)，P2.2 起由
    #: solve_linear_detail 作为固定背景从 y_obs 扣除（此前 GUI 收集了
    #: 却从未接进引擎）；"interp" 模式由 solve() 自动提取后归一化为 manual
    bg_points: tuple = ()
    #: "interp" 提取迭代次数（MAUD 默认 10）
    bg_interp_iters: int = 10
    # ---- v1.4.0 扩展 ----
    refine_po: bool = False          # March–Dollase 择优取向 r 精修（默认关）
    # ---- v1.3 评审降级（实验用，勿在生产路径开启）：每相 Brindley mu*r
    # 精修。已证伪：Brindley 因子是每相常数标量，与线性层每相自由 scale
    # **完全简并**（乘积 S_p·f(μr_p) 才可辨识），单谱精修数学上不可辨识，
    # 实测 LM 在零梯度平面漂移到上界（真值 2.0 → 撞界 20.0），且 Rwp 不变
    # 而 wt% 静默漂移。μ·r 请用 core.absorption 按化学成分计算或实测输入。
    # 机制保留仅供多谱联合/受约束标度等未来场景实验。
    refine_microabs: bool = False
    # ---- v1.3 任务 #14: EWIMV 离散 ODF 织构（每相 TEXTURE_N_GRID 维，默认关） ----
    # 仅精修 prm.texture 中已给出的相；开织构的相忽略 po_r（互斥）。
    refine_texture: bool = False
    #: 二阶差分光滑罚权重（欠定护栏）；0 = 关闭正则化（仅供 A4 对照实验）
    texture_lambda: float = TEXTURE_LAMBDA
    # ---- v1.3 任务 #15: Popa LB 各向异性尺寸/应变（默认关） ----
    # 仅精修 prm.aniso 中已给出的相；开该相的标量 X/Y 被每峰方向值取代。
    refine_aniso: bool = False
    #: "size"（默认，6 维）| "strain"（6 维）| "both"（12 维，可能不可辨识）。
    #: size 与 strain 都能改变峰宽的方向依赖，同时自由会被此消彼长地吸收。
    aniso_mode: str = "size"
    # ---- NCA 修改（T2.1）: TCH 尺寸/应变精修（默认关，保持 vendor 行为） ----
    refine_size: bool = False        # 精修 Y（Kλ/D，尺寸项）
    refine_strain: bool = False      # 精修 X（4ε，应变项）
    # ---- NCA 修改（T3.2）: 收敛点相关性矩阵（默认关，约 +2n 次残差评估） ----
    refine_corr: bool = False
    # ---- NCA 修改（T6.3a）: 取消钩子（callable() -> bool，True 表示请求取消） ----
    cancel_cb: object = None


@dataclass(frozen=True)
class RefineResult:
    """精修结果。phase_dropped 为被线性层剔除（scale=0）的相下标；
    restarted=True 表示角点陷阱检测触发过重启链（至少跑过一个重启起点）；
    cell_scales 为每相 (fa, fc) 晶胞缩放（refine_cell=False 时全为 1.0）；
    po_r 为精修后的每相 March–Dollase 参数 {phase: (h,k,l,r)}
    （refine_po=False 或未精修时为 None）。"""

    params: ProfileParams
    scales: np.ndarray
    bg: np.ndarray
    ycalc: np.ndarray
    rf: RFactors
    success: bool
    history: list[float] = field(default_factory=list)
    phase_dropped: list[int] = field(default_factory=list)
    restarted: bool = False
    cell_scales: list[tuple[float, float]] = field(default_factory=list)
    iters: int = 0
    po_r: dict | None = None
    # NCA 修改（T3.2，INV-3 追加字段）：收敛点相关性（corr.CorrResult），
    # refine_corr=False 时为 None。
    correlation: object = None


def _pack(prm: ProfileParams, cfg: RefineConfig, n_phase: int) -> np.ndarray:
    """按 cfg 开关把非线性参数打包成 LM 向量。

    v1.4.0：refine_po 且 prm.po_r 非空时，按 sorted(prm.po_r) 顺序把每相
    的 March–Dollase r 追加到向量**末尾**（cell 参数之后）。
    """
    x: list[float] = []
    if cfg.refine_zero:
        x.append(prm.zero)
    if cfg.refine_uvw:
        x.extend([prm.U, prm.V, prm.W])
    if cfg.refine_eta:
        x.append(prm.eta)
    if cfg.refine_asym:
        x.append(prm.asym)
    if cfg.refine_bfactor:
        x.append(prm.bfactor)
    if cfg.refine_cell:
        cs = getattr(prm, "_cell_scales", None) or [(1.0, 1.0)] * n_phase
        for fa, fc in cs:
            x.extend([fa, fc])
    if cfg.refine_po and prm.po_r:
        for name in sorted(prm.po_r):
            x.append(float(prm.po_r[name][3]))
    # v1.3: 每相 Brindley mu*r（顺序与 _unpack/_bounds 一致：sorted(microabs)）
    if cfg.refine_microabs and prm.microabs:
        for name in sorted(prm.microabs):
            x.append(float(prm.microabs[name]))
    # v1.3 #14: 每相织构网格（sorted(texture)，每相 TEXTURE_N_GRID 维）
    if cfg.refine_texture and prm.texture:
        for name in sorted(prm.texture):
            for v in normalize_texture_grid(prm.texture[name].get("grid")):
                x.append(float(v))
    # v1.3 #15: 每相各向异性（sorted(aniso)：size 6 后 strain 6）
    if cfg.refine_aniso and prm.aniso:
        kinds = _aniso_kinds(cfg)
        for name in sorted(prm.aniso):
            entry = prm.aniso[name]
            for key in kinds:
                c = list(entry.get(key) or [])
                c = (c + [0.0] * 6)[:6]
                x.extend(float(v) for v in c)
    # NCA 修改（T2.1）: X/Y 追加在最后（PO 之后），_unpack/_bounds 同序
    if cfg.refine_strain:
        x.append(float(getattr(prm, "X", 0.0)))
    if cfg.refine_size:
        x.append(float(getattr(prm, "Y", 0.0)))
    return np.array(x, dtype=np.float64) if x else np.zeros(0)


def _unpack(x: np.ndarray, base: ProfileParams, cfg: RefineConfig,
            n_phase: int) -> tuple[ProfileParams, list[tuple[float, float]]]:
    """由 LM 向量重建 (ProfileParams, 每相晶胞缩放)。未精修字段取 base 值。

    v1.4.0：PO 参数按 sorted(base.po_r) 同序重建（hkl 取 base 值、r 取 x），
    与 _pack/_bounds 三方顺序严格一致。
    """
    i = 0
    zero, U, V, W, eta = base.zero, base.U, base.V, base.W, base.eta
    asym, bfactor = base.asym, base.bfactor
    if cfg.refine_zero:
        zero = float(x[i]); i += 1
    if cfg.refine_uvw:
        U, V, W = float(x[i]), float(x[i + 1]), float(x[i + 2]); i += 3
    if cfg.refine_eta:
        eta = float(x[i]); i += 1
    if cfg.refine_asym:
        asym = float(x[i]); i += 1
    if cfg.refine_bfactor:
        bfactor = float(x[i]); i += 1
    cell = [(1.0, 1.0)] * n_phase
    if cfg.refine_cell:
        for j in range(n_phase):
            cell[j] = (float(x[i]), float(x[i + 1])); i += 2
    # NCA 修改（T2.1）: X/Y 从向量末端读回。_pack 顺序是 ...先 X 后 Y，
    # 故 Y 在最末、X 在倒数第二；只开其中一个时另一个取 base 值。
    idx = len(x)
    if cfg.refine_size:
        idx -= 1
        Y = float(x[idx])
    else:
        Y = getattr(base, "Y", 0.0)
    if cfg.refine_strain:
        idx -= 1
        X = float(x[idx])
    else:
        X = getattr(base, "X", 0.0)
    po_r = base.po_r
    if cfg.refine_po and base.po_r:
        po_r = {}
        for name in sorted(base.po_r):
            entry = base.po_r[name]
            po_r[name] = (entry[0], entry[1], entry[2], float(x[i])); i += 1
    # v1.3: mu*r 与 _pack 同序（sorted(microabs)）；X/Y 末端倒读不受影响
    microabs = base.microabs
    if cfg.refine_microabs and base.microabs:
        microabs = dict(base.microabs)
        for name in sorted(base.microabs):
            microabs[name] = max(float(x[i]), MICROABS_BOUNDS[0]); i += 1
    # v1.3 #14: 织构网格与 _pack 同序（sorted(texture)），axis 取 base 值
    texture = base.texture
    if cfg.refine_texture and base.texture:
        texture = {}
        for name in sorted(base.texture):
            entry = dict(base.texture[name])
            entry["grid"] = [max(min(float(x[i + k]), TEXTURE_BOUNDS[1]),
                                 TEXTURE_BOUNDS[0])
                             for k in range(TEXTURE_N_GRID)]
            i += TEXTURE_N_GRID
            texture[name] = entry
    # v1.3 #15: 各向异性与 _pack 同序（sorted(aniso)：size 6 后 strain 6）
    aniso = base.aniso
    if cfg.refine_aniso and base.aniso:
        aniso = {}
        def _clamp(v, k, strain):
            diag = k in ANISO_DIAG_IDX
            if strain:
                b = ANISO_STRAIN_BOUNDS if diag else ANISO_STRAIN_CROSS
            else:
                b = ANISO_SIZE_BOUNDS if diag else ANISO_SIZE_CROSS
            return max(min(float(v), b[1]), b[0])

        for name in sorted(base.aniso):
            entry = dict(base.aniso[name])
            for key in _aniso_kinds(cfg):
                entry[key] = [_clamp(x[i + k], k, key == "strain")
                              for k in range(6)]
                i += 6
            aniso[name] = entry
    prm = ProfileParams(zero=zero, U=U, V=V, W=max(W, MIN_W), eta=eta,
                        anode=base.anode, ka_ratio=base.ka_ratio,
                        po_r=po_r, wavelength=base.wavelength,
                        asym=asym, bfactor=bfactor,
                        integrated=base.integrated,
                        microabs=microabs, texture=texture, aniso=aniso,
                        X=X, Y=Y)   # NCA 修改（T2.1）
    return prm, cell


def _bounds(cfg: RefineConfig, n_phase: int,
            n_po: int = 0, n_ma: int = 0,
            n_tex: int = 0, n_aniso: int = 0) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = [], []
    if cfg.refine_zero:
        lo.append(ZERO_BOUNDS[0]); hi.append(ZERO_BOUNDS[1])
    if cfg.refine_uvw:
        # W 下限保护：防止 FWHM 退化成 0 导致除零；V 允许为负（真实数据）
        lo.extend([UVW_BOUNDS[0], V_BOUNDS[0], MIN_W])
        hi.extend([UVW_BOUNDS[1], V_BOUNDS[1], UVW_BOUNDS[1]])
    if cfg.refine_eta:
        lo.append(ETA_BOUNDS[0]); hi.append(ETA_BOUNDS[1])
    if cfg.refine_asym:
        lo.append(ASYM_BOUNDS[0]); hi.append(ASYM_BOUNDS[1])
    if cfg.refine_bfactor:
        lo.append(BFACTOR_BOUNDS[0]); hi.append(BFACTOR_BOUNDS[1])
    if cfg.refine_cell:
        for _ in range(n_phase):
            lo.extend([CELL_BOUNDS[0]] * 2); hi.extend([CELL_BOUNDS[1]] * 2)
    # v1.4.0: 每相一个 March–Dollase r（顺序与 _pack 一致：sorted(po_r)）
    for _ in range(n_po):
        lo.append(PO_BOUNDS[0]); hi.append(PO_BOUNDS[1])
    # v1.3: 每相一个 Brindley mu*r（顺序与 _pack 一致：sorted(microabs)）
    for _ in range(n_ma):
        lo.append(MICROABS_BOUNDS[0]); hi.append(MICROABS_BOUNDS[1])
    # v1.3 #14: 每相 TEXTURE_N_GRID 个 T(χ)（顺序与 _pack 一致）
    for _ in range(n_tex):
        lo.append(TEXTURE_BOUNDS[0]); hi.append(TEXTURE_BOUNDS[1])
    # v1.3 #15: 每相各向异性系数（Cholesky 下三角，按 aniso_mode 取 size/strain）
    n_kind = len(_aniso_kinds(cfg))
    for _p in range(n_aniso):
        for kk in range(n_kind):
            key = _aniso_kinds(cfg)[kk]
            for k in range(6):
                diag = k in ANISO_DIAG_IDX
                if key == "strain":
                    b = ANISO_STRAIN_BOUNDS if diag else ANISO_STRAIN_CROSS
                else:
                    b = ANISO_SIZE_BOUNDS if diag else ANISO_SIZE_CROSS
                lo.append(b[0]); hi.append(b[1])
    # NCA 修改（T2.1）: X/Y 边界（顺序与 _pack 一致：先 X 后 Y）
    if cfg.refine_strain:
        lo.append(STRAIN_BOUNDS[0]); hi.append(STRAIN_BOUNDS[1])
    if cfg.refine_size:
        lo.append(SIZE_BOUNDS[0]); hi.append(SIZE_BOUNDS[1])
    return np.array(lo), np.array(hi)


def _aniso_kinds(cfg: RefineConfig) -> tuple[str, ...]:
    """该次精修放开的各向异性系数族（顺序即向量顺序）。"""
    mode = getattr(cfg, "aniso_mode", "size")
    if mode == "both":
        return ("size", "strain")
    if mode == "strain":
        return ("strain",)
    if mode != "size":
        raise ValueError(f"未知 aniso_mode: {mode!r}（可选 size / strain / both）")
    return ("size",)


def _ensure_po_r(phases: list[CifStructure], prm0: ProfileParams,
                 cfg: RefineConfig) -> dict | None:
    """refine_po 时按 DEFAULT_PO_HKL 给缺相补 (h,k,l,1.0) 起点。

    调用方已显式给出的 po_r 条目尊重原值，只补缺失；refine_po=False、
    没有已知惯习面相（如仅附加 CIF）或 prm0.po_r 为空且无相可补时返回
    None（该次精修不涉及 PO 参数）。

    NCA 修改（T8.1）：refine_po=False 时**保留**调用方给的 po_r 作为
    固定参数，不再一律清成 None。两段峰形精修的段 2（`pipeline.py`
    `_run_stage1b`）以段 1 精好的 r 为**固定值**传入（refine_po=False），
    此前这里清空导致段 2 的正向模型丢掉择优取向 —— 凡 r≠1 的样品段 2
    整体劣化（合成 round-trip 实测 Rwp 13.2→16.3 %、TCH 尺寸项被带进
    角点）。真实 NCA_80_15_05 样品 r≈1.000 恰好掩盖了此缺陷，round-trip
    抓出。调用方不传 po_r（prm0.po_r=None）时行为与 vendor 逐位一致。
    """
    if not cfg.refine_po:
        return dict(prm0.po_r) if prm0.po_r else None
    po_r = dict(prm0.po_r) if prm0.po_r else {}
    for st in phases:
        if st.name in po_r:
            continue
        hkl = DEFAULT_PO_HKL.get(st.name)
        if hkl is None:
            continue
        po_r[st.name] = (int(hkl[0]), int(hkl[1]), int(hkl[2]), 1.0)
    return po_r or None


def _scaled(struct: CifStructure, fa: float, fc: float) -> CifStructure:
    """四方晶系晶胞 a,c 缩放（b 同 a；角度不变的轴缩放不改变原子分数坐标）。"""
    if abs(fa - 1.0) < 1e-12 and abs(fc - 1.0) < 1e-12:
        return struct
    a, b, c, al, be, ga = struct.cell
    return CifStructure(struct.name, (a * fa, b * fa, c * fc, al, be, ga),
                        struct.atoms)


def _check_cancel(cfg: RefineConfig) -> None:
    """NCA 修改（T6.3a）：若 `cancel_cb` 请求取消则抛 :class:`RefineCancelled`。

    放在残差函数入口 —— LM 每轮迭代要评估 n+1 次残差，scipy trf 后端同理，
    这里是两个后端都覆盖、且响应最快的检查点。

    回调自身的异常按 vendor 惯例**吞掉**（进度/迭代回调不许影响精修），
    但 `RefineCancelled` 必须透传，否则取消就失效了。
    """
    cb = getattr(cfg, "cancel_cb", None)
    if cb is None:
        return
    try:
        if cb():
            raise RefineCancelled()
    except RefineCancelled:
        raise
    except Exception:
        pass


def _registry_for(cfg: RefineConfig, prm: ProfileParams,
                  n_phase: int) -> ParameterRegistry:
    """由 cfg + 当前参数构造声明式注册表（P1.0c 生产路径唯一入口）。

    PO 槽位名取 ``sorted(prm.po_r)``、microabs 槽位名取 ``sorted(prm.microabs)``，
    与旧 ``_pack`` 的顺序一致；
    ``build_registry_from_config`` 只依赖开关与槽位名，不依赖参数数值，
    故可在残差闭包外**构造一次**复用（热路径不重复建注册表）。
    """
    po_names = sorted(prm.po_r) if prm.po_r else []
    return build_registry_from_config(cfg, prm, n_phase, po_names)


def _unpack_reg(reg: ParameterRegistry, x: np.ndarray, base: ProfileParams):
    """registry.unpack 的三元组结果适配旧 ``_unpack`` 的二元组契约。"""
    prm, cell, _po = reg.unpack(x, base, po_r=base.po_r)
    return prm, cell


def effective_sigma(cfg: RefineConfig, pat: Pattern,
                    ycalc: np.ndarray | None = None) -> np.ndarray:
    """统一取 σ 入口（v1.2.0，对照 MAUD ``DiffrDataFile.getWeight`` 的 4 模式）。

    - ``cfg.sigma`` 显式给出时**总是**优先（老调用方/测试契约不变）；
    - ``weight_mode="sqrt"``：1/σ ∝ 1/√y（计数统计），与 v1.1.x 逐位一致；
    - ``"file"``：谱图 ``meta["sigma"]``（``_pd_meas_intensity_sigma``），
      缺失/形状不符/非正时**回退** sqrt 并不报错（宽松加载）；
    - ``"unit"``：常数权（σ=1），等价 MAUD case 3；
    - ``"1/y"``：σ=y（夹到 ≥1），等价 MAUD case 2；
    - ``"theoretical"``（v1.3）：σ=√max(ycalc,1)，MAUD theoreticalWeights，
      用**计算值**代替观测值定权（抗弱峰噪声漂移）。``ycalc`` 省略时用
      观测值引导（引导语义，solve() 入口会先解析成固定 σ 数组再进引擎）。

    注意：Rwp 的权重与残差权重共用本函数（口径一致，否则 Rwp 失去可比性）。
    """
    if cfg.sigma is not None:
        return cfg.sigma
    yo = pat.intensity
    mode = cfg.weight_mode
    if mode == "sqrt":
        return np.sqrt(np.maximum(yo, 1.0))
    if mode == "unit":
        return np.ones_like(yo)
    if mode == "1/y":
        return np.maximum(yo, 1.0)
    if mode == "theoretical":
        ref = yo if ycalc is None else ycalc
        return np.sqrt(np.maximum(np.asarray(ref, dtype=np.float64), 1.0))
    if mode == "file":
        sig = pat.meta.get("sigma")
        if sig is not None:
            sig = np.asarray(sig, dtype=np.float64)
            if sig.shape == yo.shape and bool(np.all(sig > 0)):
                return sig
        return np.sqrt(np.maximum(yo, 1.0))
    raise ValueError(
        f"未知 weight_mode: {mode!r}（可选 sqrt / file / unit / 1/y / theoretical）")


def _build_residual(phases: list[CifStructure], pat: Pattern, base: ProfileParams,
                    cfg: RefineConfig, history: list[float], gen: list[int],
                    reg: ParameterRegistry | None = None):
    """构造变量投影残差函数（闭包，含每相晶胞缩放缓存）。

    P1.0c：``reg`` 由 :func:`refine` 在外部构造并传入；残差评估这一热路径
    只做 ``reg.unpack``，不重建注册表。``reg=None`` 时退化为就地构造（兼容
    旧调用方/测试，不影响数值）。
    """
    tt, yo = pat.two_theta, pat.intensity
    sig = effective_sigma(cfg, pat)
    if reg is None:
        reg = _registry_for(cfg, base, len(phases))
    cell_cache: dict[tuple, CifStructure] = {}

    def scaled(si: int, fa: float, fc: float) -> CifStructure:
        key = (si, round(fa, 9), round(fc, 9))
        hit = cell_cache.get(key)
        if hit is None:
            hit = _scaled(phases[si], fa, fc)
            cell_cache[key] = hit
        return hit

    def residual_fn(x: np.ndarray) -> np.ndarray:
        _check_cancel(cfg)          # NCA 修改（T6.3a）：先看要不要中止
        prm, cell = _unpack_reg(reg, x, base)
        rows = [compute_phase_profile(
                    scaled(si, fa, fc), tt, prm, cfg.tmin, cfg.tmax)
                for si, (fa, fc) in enumerate(cell)]
        basis = np.vstack(rows) if rows else np.zeros((0, tt.size))
        _coeffs, ycalc, _dropped = solve_linear_detail(
            basis, tt, yo, sig, cfg.n_bg, cfg.bg_mode,
            bg_points=list(cfg.bg_points) or None)
        # history 记录每次评估的 Rwp（GSAS-II 口径，背景计入）
        rwp = compute_rfactors(
            yo, ycalc, n_params=x.size + basis.shape[0] + cfg.n_bg).rwp
        history.append(rwp)
        gen[0] += 1
        if cfg.on_iter is not None:
            try:
                cfg.on_iter(gen[0], rwp)
            except Exception:
                pass
        r = (yo - ycalc) / sig
        # v1.3 #14：织构 T(χ) 正则化 —— 二阶差分光滑罚（λ=0 关闭）
        # + 末端节点锚定 1.0（消除「T 乘常数 ↔ scale 除常数」零空间）
        if cfg.refine_texture and prm.texture:
            lam = float(getattr(cfg, "texture_lambda", 0.0) or 0.0)
            pen = []
            for name in sorted(prm.texture):
                g = np.asarray(normalize_texture_grid(
                    prm.texture[name].get("grid")), dtype=np.float64)
                if lam > 0.0:
                    pen.append(np.sqrt(lam) * (g[:-2] - 2.0 * g[1:-1] + g[2:]))
                pen.append(np.array([TEXTURE_ANCHOR_W * (g[-1] - 1.0)]))
            if pen:
                r = np.concatenate([r] + pen)
        return r

    return residual_fn, scaled


def _rwp_at(phases: list[CifStructure], pat: Pattern, prm: ProfileParams,
            cfg: RefineConfig) -> float:
    """给定非线性参数下的 Rwp（解一次线性层），用于重启选点。

    注意：重启选点评估不缩放晶胞（cell=1.0），只比较峰形参数的优劣。
    """
    tt, yo = pat.two_theta, pat.intensity
    sig = effective_sigma(cfg, pat)
    rows = [compute_phase_profile(s, tt, prm, cfg.tmin, cfg.tmax)
            for s in phases]
    _coeffs, ycalc, _dropped = solve_linear_detail(
        np.vstack(rows), tt, yo, sig, cfg.n_bg, cfg.bg_mode,
        bg_points=list(cfg.bg_points) or None)
    return compute_rfactors(yo, ycalc, n_params=cfg.n_bg).rwp


def _restart_points(prm_try: ProfileParams) -> list[ProfileParams]:
    """确定性修复起点（LM 角点陷阱的解药）。

    现象: 从 U=V=0 角点出发时 LM 会把 W 吸到下界、用 V 补偿，掉进 Rwp≈14~25%
    的浅极小且 λ 溢出无法逃逸（v75 实测）。任何 U>0 的起点都能收敛到全局盆。
    触发条件: LM 失败 / Rwp>10% / W 触界，用下面的点重试并保留最优。
    """
    pts = []
    for u, w in ((0.02, 0.02), (0.05, 0.01), (0.0, 0.02)):
        # 用 replace 保留全部其余字段（X/Y、microabs、texture、aniso、po_r）：
        # 早先手工重建 ProfileParams 会把这些扩展字段静默清零，重启后
        # 织构/各向异性/微吸收全部失效（v1.3 实测 registry.pack 直接崩溃）。
        pts.append(replace(prm_try, U=u, V=0.0, W=w))
    return pts


def refine(phases: list[CifStructure], pat: Pattern, prm0: ProfileParams,
           cfg: RefineConfig) -> RefineResult:
    """Rietveld 精修主入口（变量投影 + 自写 LM + 确定性多起点重启）。

    phases: 相列表（CifStructure，name 需与 prm0.po_r 的键对应）
    pat   : 实测/合成谱（Pattern）
    prm0  : 非线性参数初值（可含 asym/bfactor/po_r 初值）
    cfg   : 精修开关（v1.0.0 起支持 bg_mode/asym/bfactor/cell/进度回调；
             v1.4.0 起支持 refine_po：March–Dollase 择优取向 r 精修，
             缺相按 DEFAULT_PO_HKL 补 (h,k,l,1.0) 起点，结果见
             RefineResult.po_r）
    """
    if cfg.progress_cb is not None:
        try:
            cfg.progress_cb("正在初始化精修模型…", None)
        except Exception:
            pass
    history: list[float] = []
    gen = [0]
    n_phase = len(phases)
    # v1.4.0: refine_po 时按内置惯习面补缺失相的 (h,k,l,1.0) 起点
    prm0 = replace(prm0, po_r=_ensure_po_r(phases, prm0, cfg))
    # P1.0c：生产路径全程走声明式注册表；x0 / bounds / unpack 均出自 reg，
    # 旧 _pack/_bounds/_unpack 仅保留为兼容 API 与双轨回归参照。
    reg = _registry_for(cfg, prm0, n_phase)
    x0 = reg.pack(prm0, po_r=prm0.po_r)
    residual_fn, scaled_fn = _build_residual(phases, pat, prm0, cfg, history,
                                             gen, reg=reg)

    if x0.size:
        lo, hi = reg.bounds()
        # v1.3 #16：优化器可插拔（lm 默认 / trf / dogbox，见 optimizers 模块）。
        # scipy 后端在真实数据（多相关联形状参数）上更稳，能守住内部解不
        # 落入 U,V→0 角点（v1.0.0 实证，Rwp 11.6→9.5%）。
        def _progress(n: int) -> None:
            if cfg.progress_cb is None or n % 40:
                return
            try:
                cfg.progress_cb(
                    f"正在 Rietveld 全谱拟合（已评估 {n} 次）…", None)
            except Exception:
                pass

        opt = _optimize(residual_fn, x0, (lo, hi), method=cfg.backend,
                        max_iter=cfg.max_iter, on_eval=_progress)
        best_x, best_cost, success = opt.x, opt.cost, opt.success
        # ---- 多起点重启（仅 refine_uvw）: 角点陷阱检测 ----
        restarted = False
        if cfg.refine_uvw:
            prm_try, _cell = _unpack_reg(reg, best_x, prm0)
            stuck = (not success) or prm_try.W <= 2.0 * MIN_W
            if not stuck:
                # 用含晶胞缩放的完整模型重评估一次（_rwp_at 不缩放晶胞，
                # 会在正常收敛点误报 >10% 而触发无用的 LM 重启）
                residual_fn(best_x)
                stuck = history[-1] > 10.0
            if stuck:
                restarted = True
                for cand in _restart_points(prm_try):
                    r2, _sf2 = _build_residual(phases, pat, cand, cfg,
                                               history, gen, reg=reg)
                    lm2 = _optimize(r2, reg.pack(cand, po_r=cand.po_r),
                                    (lo, hi), method=cfg.backend,
                                    max_iter=cfg.max_iter)
                    if lm2.cost < best_cost:
                        best_x, best_cost = lm2.x, lm2.cost
                        success = lm2.success
    else:
        # 无非线性自由度：只解一次线性层
        best_x, success = x0, True
        restarted = False
        residual_fn(best_x)

    prm, cell_scales = _unpack_reg(reg, best_x, prm0)
    _check_cancel(cfg)          # NCA 修改（T6.3a）：合成最终计算谱前再看一次
    # NCA 修改（T3.2）：收敛点相关性矩阵（refine_corr=True 时计算）
    correlation = None
    if cfg.refine_corr and best_x.size:
        from xinrefinement.core.refine.corr import CorrResult, corr_from_jacobian, pack_labels
        from xinrefinement.core.refine.lm import _jacobian as _lm_jac
        po_names = (sorted(prm0.po_r)
                    if (cfg.refine_po and prm0.po_r) else [])
        labels = pack_labels(cfg, n_phase, po_names)
        J = _lm_jac(residual_fn, best_x)
        correlation = CorrResult(labels=labels,
                                 matrix=corr_from_jacobian(J))
    if cfg.progress_cb is not None:
        try:
            cfg.progress_cb("正在合成最终计算谱…", 0.95)
        except Exception:
            pass
    rows = [compute_phase_profile(
                _scaled(phases[si], fa, fc), pat.two_theta, prm,
                cfg.tmin, cfg.tmax)
            for si, (fa, fc) in enumerate(cell_scales)]
    basis = np.vstack(rows)
    sig_final = effective_sigma(cfg, pat)
    coeffs, ycalc, dropped = solve_linear_detail(
        basis, pat.two_theta, pat.intensity,
        sig_final, cfg.n_bg, cfg.bg_mode,
        bg_points=list(cfg.bg_points) or None)
    n_p = best_x.size + basis.shape[0] + cfg.n_bg
    rf = compute_rfactors(pat.intensity, ycalc, n_params=n_p,
                          sigma=sig_final, include_bg=True)
    return RefineResult(params=prm, scales=coeffs[:basis.shape[0]].copy(),
                        bg=coeffs[basis.shape[0]:].copy(), ycalc=ycalc,
                        rf=rf, success=success, history=history,
                        phase_dropped=dropped, restarted=restarted,
                        cell_scales=cell_scales, iters=gen[0],
                        po_r=prm.po_r if cfg.refine_po else None,
                        correlation=correlation)
