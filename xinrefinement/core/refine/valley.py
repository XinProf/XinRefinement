"""TCH 尺寸项的「谷扫描」初值机制（T8.1 引入，T8.2 补边界让位）。

**为什么单独成模块**：`nca/core/pipeline.py` 曾达 513 行，超「单文件 ≤400
行」的硬约束。谷扫描是**独立的数值子问题**（给定脉形参数找出 (U,V,W)↔Y
联合代价谷的谷底），不依赖管线状态，可脱离管线单测 —— 因此整块外移。

**要解决的问题**：段 1 不开 TCH 时，晶粒尺寸展宽会被 Caglioti 项
U/V/W 吸收（对无 TCH 的模型来说那确实是最优解）。段 1b 从被污染的
起点出发，而 (U,V,W)↔Y 的联合代价谷是**弯的** —— 普通初值的 LM 初始
梯度只指向「Y→0 + UVW 回吸」的假盆地（实测三种起点三种结局：
Y→0 / U=0.25 / 真值，随机落点）。

**解法**：沿「总 FWHM 守恒」方向确定性扫描。对候选 Y₀ 用 TCH 逆解
（`gamma_g_from_total`）算出允许的高斯份额，按同一比例缩 U/V/W，使
初值直接落在谷上；每点只做 forward + 线性最小二乘（不跑 LM），
14 点网格约秒级。

调用方（`pipeline._run_stage1b`）把谷底初值与普通初值**各跑一次联合
LM**，再按 `_pick_candidate` 择优（含边界解让位）。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from xinrefinement.core.profile.cif import CifStructure

if TYPE_CHECKING:                      # 仅注解，避免运行时循环导入
    from xinrefinement.core.dtypes import Pattern
    from xinrefinement.core.profile.forward import ProfileParams
    from xinrefinement.core.solve import SolveOptions

#: 谷扫描的 Y 网格（度）：0.02–0.15，覆盖 D ≈ 500–65 nm（Cu 靶）。
#: 步长 0.01 —— 谷底定位误差 ≤ 半步，随后的联合 LM 会收敛到精确解。
VALLEY_GRID = tuple(round(0.02 + 0.01 * i, 3) for i in range(14))

#: 谷扫描用缩放结构的缓存盐值（防 forward 峰缓存 id 复用错配）
_SCAN_VARIANT = itertools.count(10_000_000)


def gamma_g_from_total(total: float, gl: float) -> float:
    """TCH 逆解：给定总 FWHM 与洛伦兹份额，二分求高斯份额。

    `tch_combine(ΓG, ΓL)` 对 ΓG 严格单调递增，二分全局收敛。
    """
    from xinrefinement.core.profile.size_strain import tch_combine

    lo, hi = 1e-6, total
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if tch_combine(mid, gl) < total:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def valley_scan(pat: Pattern, structure: CifStructure, prm0: ProfileParams,
                cell_scales, so: SolveOptions) -> float:
    """沿「总 FWHM 守恒」谷扫描 TCH 尺寸项 Y（度），返回谷底 Y*。

    谷的方向 = 总 FWHM 近似不变：对候选 Y0，用 TCH 逆解算出允许的
    高斯份额，按同一比例缩 U/V/W（ΓG² = U·tan²θ + V·tanθ + W，三者
    同乘 k² 等价于 ΓG 乘 k，对全部角度成立）—— 初值即落在谷上。
    段 1 的晶胞缩放已施加（否则峰位错开、扫描无意义）。

    返回 0.0 表示扫描不可用（无有效网格点），调用方回退常量初值。
    """
    from xinrefinement.core.profile.forward import (
        caglioti_2theta, compute_phase_profile, width_function)
    from xinrefinement.core.refine.linear import background_basis
    from xinrefinement.core.solve import _focus          # noqa: SLF001 —— 包内私有复用

    fp = _focus(pat, so)
    tt, yo = fp.two_theta, fp.intensity
    fa, fc = cell_scales[0] if cell_scales else (1.0, 1.0)
    a, b, c, al, be, ga = structure.cell
    st_sc = CifStructure(structure.name, (a * fa, b * fa, c * fc, al, be, ga),
                         structure.atoms)
    st_sc._variant = next(_SCAN_VARIANT)     # noqa: SLF001 —— 有意公开的盐值位
    pos_ref = 0.5 * (so.tmin + so.tmax)
    th_ref = math.radians(pos_ref / 2.0)
    gtot0 = (width_function(prm0)
             if getattr(prm0, "width_basis", "tan") == "d"
             else caglioti_2theta(prm0.U, prm0.V, prm0.W))(pos_ref)
    if gtot0 <= 0.0:
        return 0.0
    sig2 = 1.0 / np.maximum(yo, 1.0)
    w = np.sqrt(sig2)
    bb = background_basis(tt, so.n_bg, so.bg_mode)
    best_y, best_cost = 0.0, math.inf
    for y0 in VALLEY_GRID:
        gl = y0 / math.cos(th_ref)
        if gl >= gtot0:
            continue
        gg = gamma_g_from_total(gtot0, gl)
        k = gg / gtot0
        prm = replace(prm0, U=prm0.U * k * k, V=prm0.V * k * k,
                      W=prm0.W * k * k, Y=y0)
        basis = np.asarray(
            compute_phase_profile(st_sc, tt, prm, so.tmin, so.tmax),
            dtype=float).ravel()
        amat = np.column_stack([basis, bb])
        coef, *_ = np.linalg.lstsq(amat * w[:, None], yo * w, rcond=None)
        yc = amat @ coef
        cost = float(np.sum(sig2 * (yo - yc) ** 2)
                     / np.sum(sig2 * yo * yo))
        if cost < best_cost:
            best_cost, best_y = cost, y0
    return best_y


def valley_init(prm0: ProfileParams, y_star: float, so: SolveOptions):
    """由谷底 Y* 构造联合精修初值：UVW 按谷方向缩放，Y/X 置谷底/常量。"""
    from xinrefinement.core.profile.forward import (
        caglioti_2theta, width_function)

    pos_ref = 0.5 * (so.tmin + so.tmax)
    th_ref = math.radians(pos_ref / 2.0)
    gtot0 = (width_function(prm0)
             if getattr(prm0, "width_basis", "tan") == "d"
             else caglioti_2theta(prm0.U, prm0.V, prm0.W))(pos_ref)
    k = 1.0
    if gtot0 > 0.0:
        gl = y_star / math.cos(th_ref)
        if gl < gtot0:
            k = gamma_g_from_total(gtot0, gl) / gtot0
    return replace(prm0, U=prm0.U * k * k, V=prm0.V * k * k,
                   W=prm0.W * k * k, Y=y_star)
