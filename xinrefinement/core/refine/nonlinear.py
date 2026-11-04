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
    MIN_W,
    ProfileParams,
    compute_phase_profile,
)
from xinrefinement.core.refine.lm import lm_minimize
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
    bg_mode: str = "cheb"            # "cheb" | "tent"
    refine_asym: bool = False        # 低角不对称尾
    refine_bfactor: bool = False     # 经验高角衰减 B
    refine_cell: bool = False        # 每相晶胞 a,c 缩放 (T4.7)
    backend: str = "lm"              # "lm"（自研，默认）| "scipy"（trf，真实数据推荐）
    progress_cb: object = None       # callable(msg: str, pct: float | None)
    on_iter: object = None           # callable(gen: int, rwp: float)
    # ---- v1.4.0 扩展 ----
    refine_po: bool = False          # March–Dollase 择优取向 r 精修（默认关）
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
    prm = ProfileParams(zero=zero, U=U, V=V, W=max(W, MIN_W), eta=eta,
                        anode=base.anode, ka_ratio=base.ka_ratio,
                        po_r=po_r, wavelength=base.wavelength,
                        asym=asym, bfactor=bfactor,
                        integrated=base.integrated,
                        X=X, Y=Y)   # NCA 修改（T2.1）
    return prm, cell


def _bounds(cfg: RefineConfig, n_phase: int,
            n_po: int = 0) -> tuple[np.ndarray, np.ndarray]:
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
    # NCA 修改（T2.1）: X/Y 边界（顺序与 _pack 一致：先 X 后 Y）
    if cfg.refine_strain:
        lo.append(STRAIN_BOUNDS[0]); hi.append(STRAIN_BOUNDS[1])
    if cfg.refine_size:
        lo.append(SIZE_BOUNDS[0]); hi.append(SIZE_BOUNDS[1])
    return np.array(lo), np.array(hi)


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

    PO 槽位名取 ``sorted(prm.po_r)``，与旧 ``_pack`` 的顺序一致；
    ``build_registry_from_config`` 只依赖开关与槽位名，不依赖参数数值，
    故可在残差闭包外**构造一次**复用（热路径不重复建注册表）。
    """
    po_names = sorted(prm.po_r) if prm.po_r else []
    return build_registry_from_config(cfg, prm, n_phase, po_names)


def _unpack_reg(reg: ParameterRegistry, x: np.ndarray, base: ProfileParams):
    """registry.unpack 的三元组结果适配旧 ``_unpack`` 的二元组契约。"""
    prm, cell, _po = reg.unpack(x, base, po_r=base.po_r)
    return prm, cell


def _build_residual(phases: list[CifStructure], pat: Pattern, base: ProfileParams,
                    cfg: RefineConfig, history: list[float], gen: list[int],
                    reg: ParameterRegistry | None = None):
    """构造变量投影残差函数（闭包，含每相晶胞缩放缓存）。

    P1.0c：``reg`` 由 :func:`refine` 在外部构造并传入；残差评估这一热路径
    只做 ``reg.unpack``，不重建注册表。``reg=None`` 时退化为就地构造（兼容
    旧调用方/测试，不影响数值）。
    """
    tt, yo = pat.two_theta, pat.intensity
    sig = cfg.sigma
    if sig is None:
        sig = np.sqrt(np.maximum(yo, 1.0))
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
            basis, tt, yo, sig, cfg.n_bg, cfg.bg_mode)
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
        return (yo - ycalc) / sig

    return residual_fn, scaled


def _rwp_at(phases: list[CifStructure], pat: Pattern, prm: ProfileParams,
            cfg: RefineConfig) -> float:
    """给定非线性参数下的 Rwp（解一次线性层），用于重启选点。

    注意：重启选点评估不缩放晶胞（cell=1.0），只比较峰形参数的优劣。
    """
    tt, yo = pat.two_theta, pat.intensity
    sig = cfg.sigma if cfg.sigma is not None else np.sqrt(np.maximum(yo, 1.0))
    rows = [compute_phase_profile(s, tt, prm, cfg.tmin, cfg.tmax)
            for s in phases]
    _coeffs, ycalc, _dropped = solve_linear_detail(
        np.vstack(rows), tt, yo, sig, cfg.n_bg, cfg.bg_mode)
    return compute_rfactors(yo, ycalc, n_params=cfg.n_bg).rwp


def _restart_points(prm_try: ProfileParams) -> list[ProfileParams]:
    """确定性修复起点（LM 角点陷阱的解药）。

    现象: 从 U=V=0 角点出发时 LM 会把 W 吸到下界、用 V 补偿，掉进 Rwp≈14~25%
    的浅极小且 λ 溢出无法逃逸（v75 实测）。任何 U>0 的起点都能收敛到全局盆。
    触发条件: LM 失败 / Rwp>10% / W 触界，用下面的点重试并保留最优。
    """
    pts = []
    for u, w in ((0.02, 0.02), (0.05, 0.01), (0.0, 0.02)):
        pts.append(ProfileParams(zero=prm_try.zero, U=u, V=0.0, W=w,
                                 eta=prm_try.eta, anode=prm_try.anode,
                                 ka_ratio=prm_try.ka_ratio, po_r=prm_try.po_r,
                                 wavelength=prm_try.wavelength,
                                 asym=prm_try.asym, bfactor=prm_try.bfactor,
                                 integrated=prm_try.integrated))
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
        use_scipy = False
        if cfg.backend == "scipy":
            try:
                from scipy.optimize import least_squares
                use_scipy = True
            except Exception:
                use_scipy = False
        if use_scipy:
            # scipy trf 后端：真实数据（多相关联形状参数）上明显更稳，
            # 能守住内部解不落入 U,V→0 角点（v1.0.0 实证，Rwp 11.6→9.5%）。
            nfev = [0]

            def counted(xv):
                nfev[0] += 1
                if (cfg.progress_cb is not None and nfev[0] % 40 == 0):
                    try:
                        cfg.progress_cb(
                            f"正在 Rietveld 全谱拟合（已评估 {nfev[0]} 次）…", None)
                    except Exception:
                        pass
                return residual_fn(xv)

            sr = least_squares(counted, x0, bounds=(lo, hi), method="trf",
                               x_scale="jac", max_nfev=3000)
            best_x, best_cost, success = sr.x, float(sr.cost), bool(sr.success)
        else:
            lm = lm_minimize(residual_fn, x0, bounds=(lo, hi),
                             max_iter=cfg.max_iter)
            best_x, best_cost, success = lm.x, lm.cost, lm.success
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
                    lm2 = lm_minimize(r2, reg.pack(cand, po_r=cand.po_r),
                                      bounds=(lo, hi), max_iter=cfg.max_iter)
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
    coeffs, ycalc, dropped = solve_linear_detail(
        basis, pat.two_theta, pat.intensity,
        cfg.sigma if cfg.sigma is not None else np.sqrt(
            np.maximum(pat.intensity, 1.0)), cfg.n_bg, cfg.bg_mode)
    n_p = best_x.size + basis.shape[0] + cfg.n_bg
    rf = compute_rfactors(pat.intensity, ycalc, n_params=n_p,
                          sigma=cfg.sigma, include_bg=True)
    return RefineResult(params=prm, scales=coeffs[:basis.shape[0]].copy(),
                        bg=coeffs[basis.shape[0]:].copy(), ycalc=ycalc,
                        rf=rf, success=success, history=history,
                        phase_dropped=dropped, restarted=restarted,
                        cell_scales=cell_scales, iters=gen[0],
                        po_r=prm.po_r if cfg.refine_po else None,
                        correlation=correlation)
