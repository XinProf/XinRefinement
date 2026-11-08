"""P1.2 · 全晶胞精修（按晶系约束的 6 参数）。

家族 P0 引擎只支持四方晶系 ``_scaled(fa, fc)``（a、c 缩放，b 跟随 a）。
本模块把它推广到**任意晶系**，按 International Tables 的晶胞度量约束
只精修自由分量，避免全 6 参数同时放开造成强相关/发散。

自由度（TASKS P1.2 冻结口径）
----------------------------
=====================  ==================================
晶系                    自由缩放分量          维度
=====================  ==================================
cubic 立方              a (a=b=c)               1
tetragonal 四方         a, c (a=b)              2
orthorhombic 正交       a, b, c                 3
hexagonal 六方          a, c (a=b)              2
trigonal 三方           a, c (a=b)              2
monoclinic 单斜         a, b, c, β              4
triclinic 三斜          a, b, c, α, β, γ        6
=====================  ==================================

角度约束：只有单斜 β 与三斜 α/β/γ 参与精修；其余晶系的角度固定为
理想值（90° 或六方 120°），不引入伪自由度。

设计原则（零回归风险）
----------------------
本模块是**独立精修引擎**（``refine_cell_full``），不修改 ``nonlinear.py``
的主路径，也不改动 ``RefineConfig`` 默认值。默认关闭时 P0/M0 golden
逐位不变；P1.0c 的 registry 在后续卡再按需接入 cell_full 槽位。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.linear import solve_linear_detail
from xinrefinement.core.refine.lm import lm_minimize
from xinrefinement.core.refine.rfactors import compute_rfactors

#: 晶系 -> 自由缩放分量键（顺序即参数向量顺序）
FREE_AXES: dict[str, tuple[str, ...]] = {
    "cubic": ("a",),
    "tetragonal": ("a", "c"),
    "orthorhombic": ("a", "b", "c"),
    "hexagonal": ("a", "c"),
    "trigonal": ("a", "c"),
    "monoclinic": ("a", "b", "c", "beta"),
    "triclinic": ("a", "b", "c", "alpha", "beta", "gamma"),
}

#: 参数边界（与家族 CELL_BOUNDS ±1% 同口径）
CELL_SCALE_BOUNDS = (0.99, 1.01)


def crystal_system_of(struct: CifStructure) -> str:
    """判定晶系：优先用 CIF 空间群元数据，缺失/未登记时用晶胞度量兜底。

    空间群信息来自 ``CifStructure.spacegroup`` / ``sg_number``（P0 的
    ``parse_cif`` 填充），经 ``core.symmetry.lookup`` 归一。
    """
    from xinrefinement.core.symmetry import lookup, lookup_by_number

    info = None
    if getattr(struct, "sg_number", None):
        try:
            info = lookup_by_number(int(struct.sg_number))
        except Exception:
            info = None
    if info is None and getattr(struct, "spacegroup", None):
        try:
            info = lookup(str(struct.spacegroup))
        except Exception:
            info = None
    if info is not None and info.crystal_system in FREE_AXES:
        return info.crystal_system
    return crystal_system_from_cell(struct.cell)


def crystal_system_from_cell(cell) -> str:
    """由晶胞度量判定晶系（CIF 无空间群时的兜底，LFP 口径）。

    判据（必要条件而非充分条件）：三边全等且三角 90° → 立方；
    两边等 → 四方；a=b 且 γ≈120° → 六方；恰一角 ≠90° → 单斜；
    否则三斜。
    """
    a, b, c, al, be, ga = [float(v) for v in cell]

    def is90(x: float) -> bool:
        return abs(x - 90.0) <= 0.5

    def eq(x: float, y: float) -> bool:
        return abs(x - y) <= 0.02 * max(abs(x), abs(y), 1e-9)

    all90 = is90(al) and is90(be) and is90(ga)
    if all90:
        if eq(a, b) and eq(b, c):
            return "cubic"
        if eq(a, b) or eq(b, c) or eq(a, c):
            return "tetragonal"
        return "orthorhombic"
    if is90(al) and is90(be) and abs(ga - 120.0) <= 0.5 and eq(a, b):
        return "hexagonal"
    n90 = sum(is90(x) for x in (al, be, ga))
    if n90 == 2:
        return "monoclinic"
    return "triclinic"


def free_axes(system: str) -> tuple[str, ...]:
    """返回该晶系的自由缩放分量键（顺序固定）。"""
    try:
        return FREE_AXES[system]
    except KeyError as exc:
        raise ValueError(f"未知晶系: {system!r}") from exc


def _expand_scales(system: str, values,
                   axes: tuple[str, ...] | None = None) -> dict[str, float]:
    """把自由分量向量展开成 6 个缩放因子（非自由轴跟随/固定）。

    - 立方：a=b=c 同缩放；
    - 四方/六方/三方：b 跟随 a；
    - 角度：仅单斜 β / 三斜 α,β,γ 参与，其余固定 1.0。

    ``axes``（v1.6）：用户勾选的自由分量子集。``None`` = 按晶系全放开
    （历史行为，逐位不变）。给了子集时**只**放开其中列出的轴，其余保持
    1.0；晶系的跟随关系仍然生效（四方只勾 a 时 b 跟着 a）。
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    axes = tuple(axes) if axes is not None else free_axes(system)
    if v.size != len(axes):
        raise ValueError(f"{system} 需 {len(axes)} 个缩放因子，收到 {v.size}")
    d = dict(zip(axes, (float(x) for x in v)))
    if system == "cubic":
        d = {"a": d.get("a", 1.0), "b": d.get("a", 1.0), "c": d.get("a", 1.0)}
    elif system in ("tetragonal", "hexagonal", "trigonal"):
        d["b"] = d.get("a", 1.0)
    return {
        "a": float(d.get("a", 1.0)), "b": float(d.get("b", 1.0)),
        "c": float(d.get("c", 1.0)),
        "alpha": float(d.get("alpha", 1.0)),
        "beta": float(d.get("beta", 1.0)),
        "gamma": float(d.get("gamma", 1.0)),
    }


def resolve_axes(system: str, requested=None) -> tuple[str, ...]:
    """把用户请求的自由分量收敛到该晶系**允许**的集合（v1.6）。

    - ``requested is None`` → 该晶系全部自由分量（历史行为）；
    - 显式空序列 → 空（该相不参与晶胞精修）；
    - 非法轴（如立方给 ``b``、四方给 ``alpha``）静默丢弃 —— 那些轴在
      该晶系里不是自由度，放进来只会制造零空间。
    """
    allowed = free_axes(system)
    if requested is None:
        return allowed
    return tuple(ax for ax in allowed if ax in set(requested))


#: 重建 ``CifStructure`` 时必须原样搬运的元数据。
#: 漏搬任意一项都会造成**静默**退化而非报错：``formula``/``z_declared``
#: 缺了 QPA 直接返回 ``weight_pct=None``；``spacegroup``/``sg_number`` 缺了
#: ``crystal_system_of`` 退化成按晶胞度量猜、位点精修拿不到对称约束。
_CELL_META = ("n_asym", "n_sym_ops", "spacegroup", "sg_number",
              "formula", "z_declared", "source_path")


def structure_with_cell(struct: CifStructure, cell) -> CifStructure:
    """把新晶胞套到结构上（原子分数坐标不变），并搬走全部元数据。

    ``refine_cell_full`` 只回传 6 个晶胞参数（``CellRefineResult.cells``），
    调用方必须用它重建结构。配方 cell 步、CLI、GUI 回写都走这里，
    保证「精修过晶胞」与「没精修过」的结构在 QPA/对称处理上等价。
    """
    out = CifStructure(struct.name,
                       tuple(float(x) for x in cell), struct.atoms)
    for attr in _CELL_META:
        setattr(out, attr, getattr(struct, attr, None))
    return out


def apply_cell_scales(struct: CifStructure, system: str,
                      values, axes: tuple[str, ...] | None = None
                      ) -> CifStructure:
    """按晶系约束把缩放因子施加到晶胞，返回新 ``CifStructure``。

    原子**分数坐标不变**（晶胞参数变化不改变分数坐标），与 P0 的
    ``_scaled`` 同一口径。缩放全 1.0 时原样返回（避免无谓拷贝）。

    ``axes``（v1.6）：与 :func:`_expand_scales` 同一套自由分量子集。
    """
    s = _expand_scales(system, values, axes)
    if all(abs(v - 1.0) < 1e-12 for v in s.values()):
        return struct
    a, b, c, al, be, ga = struct.cell
    new_cell = (a * s["a"], b * s["b"], c * s["c"],
                al * s["alpha"], be * s["beta"], ga * s["gamma"])
    return structure_with_cell(struct, new_cell)


@dataclass(frozen=True)
class CellRefineResult:
    """全晶胞精修结果。"""

    systems: tuple[str, ...]
    scales: tuple[tuple[float, ...], ...]   # 每相的自由分量缩放
    cells: tuple[tuple[float, ...], ...]    # 每相精修后的 6 参数
    cells_true: tuple[tuple[float, ...], ...] | None  # 若提供真值则回填
    rwp: float
    success: bool
    history: tuple[float, ...]
    iters: int
    #: v1.6：每相**实际**参与精修的自由分量（受晶系约束与用户勾选共同
    #: 限制）。GUI 的晶胞结果表用它说明「这一相修了哪几个参数」。
    axes: tuple[tuple[str, ...], ...] = ()


def refine_cell_full(phases: list[CifStructure], pat: Pattern,
                     prm0: ProfileParams, cfg,
                     backend: str = "lm",
                     true_scales: list | None = None,
                     axes_override: dict[str, tuple[str, ...]] | None = None,
                     ) -> CellRefineResult:
    """独立全晶胞精修（变量投影 + LM/scipy-trf，与 P0 引擎同构）。

    ``cfg`` 只需提供 ``tmin/tmax/n_bg/bg_mode/sigma/max_iter``；晶胞参数
    是本引擎**唯一**的非线性自由度，峰形参数保持 ``prm0`` 固定。

    参数向量 = 各相自由晶胞缩放因子顺序拼接，边界 ±1%。

    ``axes_override``（v1.6）：``{相名: 要精修的轴}``，来自 GUI 晶胞弹窗
    的勾选。``None`` = 按晶系全放开（历史行为，逐位不变）；显式空序列 =
    该相跳过。非法轴（立方给 ``b`` 之类）由 :func:`resolve_axes` 丢弃。
    """
    from xinrefinement.core.refine.nonlinear import RefineConfig, effective_sigma

    if isinstance(cfg, RefineConfig):
        tmin, tmax = cfg.tmin, cfg.tmax
        n_bg, bg_mode = cfg.n_bg, cfg.bg_mode
        max_iter = cfg.max_iter
        sig = effective_sigma(cfg, pat)
    else:
        tmin, tmax = getattr(cfg, "tmin", 5.0), getattr(cfg, "tmax", 90.0)
        n_bg, bg_mode = getattr(cfg, "n_bg", 3), getattr(cfg, "bg_mode", "cheb")
        max_iter = getattr(cfg, "max_iter", 40)
        sigma = getattr(cfg, "sigma", None)
        sig = (np.sqrt(np.maximum(pat.intensity, 1.0)) if sigma is None
               else np.asarray(sigma, dtype=np.float64))

    systems = tuple(crystal_system_of(s) for s in phases)
    # v1.6：每相实际自由分量 = 晶系允许 ∩ 用户勾选
    over = axes_override or {}
    axes_list = tuple(
        resolve_axes(systems[i], (over.get(phases[i].name)
                                  if phases[i].name in over else None))
        for i in range(len(phases)))

    # v1.2.0：interp 与 solve() 同口径 —— 提取一次固定锚点（两层可加语义
    # 由 solve_linear_detail 的 interp 分支实现：固定层 + Chebyshev）
    bg_points = list(getattr(cfg, "bg_points", ()) or ())
    if bg_mode == "interp" and not bg_points:
        from xinrefinement.core.refine.linear import interp_background_nodes
        bg_points = interp_background_nodes(
            pat.two_theta, pat.intensity, n_bg,
            getattr(cfg, "bg_interp_iters", 10))

    dims = tuple(len(a) for a in axes_list)
    offsets = np.cumsum((0,) + dims).tolist()

    tt, yo = pat.two_theta, pat.intensity
    history: list[float] = []
    cache: dict[tuple, CifStructure] = {}

    def scaled(i: int, vals) -> CifStructure:
        key = (i, *[round(float(v), 9) for v in vals])
        hit = cache.get(key)
        if hit is None:
            hit = apply_cell_scales(phases[i], systems[i], vals, axes_list[i])
            cache[key] = hit
        return hit

    def residual_fn(x: np.ndarray) -> np.ndarray:
        structs = [scaled(i, x[offsets[i]:offsets[i + 1]])
                   for i in range(len(phases))]
        rows = [compute_phase_profile(s, tt, prm0, tmin, tmax) for s in structs]
        basis = np.vstack(rows) if rows else np.zeros((0, tt.size))
        bg_pts = bg_points
        _c, ycalc, _d = solve_linear_detail(basis, tt, yo, sig, n_bg, bg_mode,
                                            bg_points=bg_pts or None)
        rwp = compute_rfactors(yo, ycalc, n_params=x.size + basis.shape[0] + n_bg,
                               sigma=sig).rwp
        history.append(rwp)
        return (yo - ycalc) / sig

    n = sum(dims)
    x0 = np.ones(n, dtype=np.float64)
    lo = np.full(n, CELL_SCALE_BOUNDS[0])
    hi = np.full(n, CELL_SCALE_BOUNDS[1])

    if n == 0:
        residual_fn(x0)
        best_x, success = x0, True
    else:
        # v1.3 #16：统一走优化器注册表（lm / trf / dogbox，别名 scipy = trf）
        from xinrefinement.core.refine.optimizers import minimize as _optimize
        opt = _optimize(residual_fn, x0, (lo, hi), method=backend,
                        max_iter=max_iter)
        best_x, success = opt.x, opt.success

    scales = tuple(tuple(float(v) for v in best_x[offsets[i]:offsets[i + 1]])
                   for i in range(len(phases)))
    cells = tuple(tuple(float(v) for v in
                        apply_cell_scales(phases[i], systems[i],
                                          scales[i], axes_list[i]).cell)
                  for i in range(len(phases)))
    # 末次评估保证 rwp 对应最终解
    residual_fn(best_x)
    return CellRefineResult(
        systems=systems, scales=scales, cells=cells,
        cells_true=(None if true_scales is None
                    else tuple(tuple(float(v) for v in t) for t in true_scales)),
        rwp=float(history[-1]), success=bool(success),
        history=tuple(history), iters=len(history), axes=axes_list)
