"""P2.8 · Le Bail 全谱拟合（无结构强度提取）。

与 Rietveld 的区别
------------------
Rietveld 用结构因子 |F_hkl|² 决定每个衍射峰的积分强度；Le Bail 把
**每个 hkl 的积分强度当作自由变量**，按 Rietveld 分解迭代更新：

    I_hkl^(k+1) = I_hkl^(k) · Σ_i [ w_i · y_obs_i · φ_hkl(x_i − pos_hkl) ]
                            / Σ_i [ w_i · y_calc_i · φ_hkl(x_i − pos_hkl) ]

其中 φ 是单位积分面积的峰形。这样即使结构模型不完整（未知原子坐标、
无定形相），也能提取峰强度并做**晶胞/峰形精修与多相定量**。

实现口径
--------
- 峰位来自结构枚举（``compute_peaks`` 只取 pos，不用 |F|²）；
- 峰形用家族 ``_pv_peak``（pseudo-Voigt），积分强度口径归一化；
- 每次迭代按上述乘性更新逐峰强度，再用线性层解背景/总标度；
- 收敛判据：Rwp 相对变化 < tol 或达到 max_cycles。

独立引擎，不改 nonlinear.py 主路径（golden 零风险）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams, width_function
from xinrefinement.core.profile.shape import _pv_peak
from xinrefinement.core.profile.struct import compute_peaks
from xinrefinement.core.refine.linear import solve_linear_detail
from xinrefinement.core.refine.rfactors import compute_rfactors


@dataclass(frozen=True)
class LeBailResult:
    rwp: float
    rp: float
    rexp: float
    chi2: float
    intensities: tuple[tuple[float, ...], ...]  # 每相逐峰积分强度
    positions: tuple[tuple[float, ...], ...]    # 每相逐峰 2θ
    ycalc: np.ndarray
    history: tuple[float, ...]
    cycles: int
    converged: bool


def _peak_positions(struct: CifStructure, prm: ProfileParams,
                    tmin: float, tmax: float) -> np.ndarray:
    from xinrefinement.core.profile.shape import resolve_wavelengths
    comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
    peaks, _skipped = compute_peaks(struct, prm.wavelength, tmin, tmax,
                                    wavelengths=comps)
    return np.array([p[0] for p in peaks], dtype=float)


def _profile_matrix(grid: np.ndarray, positions: np.ndarray,
                    prm: ProfileParams) -> np.ndarray:
    """每列 = 单位积分面积的 pseudo-Voigt 峰（只在 ±8 FWHM 窗口内非零）。"""
    fwhm_fn = width_function(prm)   # v1.5 M5：尊重 prm.width_basis
    out = np.zeros((grid.size, positions.size), dtype=np.float64)
    for j, pos in enumerate(positions):
        fwhm = max(fwhm_fn(pos), 1e-4)
        half = 8.0 * fwhm + 0.05
        i0 = max(int(np.searchsorted(grid, pos - half, "left")), 0)
        i1 = min(int(np.searchsorted(grid, pos + half, "right")), grid.size)
        if i1 <= i0:
            continue
        shape = _pv_peak(grid[i0:i1], pos, fwhm, prm.eta)
        # 与 forward._add_peak_windowed 同口径：integrated=True 按积分面积
        # 归一化，False 为峰高口径（P0 合成谱用 False，必须对齐否则
        # Le Bail 的逐峰强度与观测谱差一个角度相关系数）。
        if prm.integrated:
            area = fwhm * (1.06447 + 0.50633 * prm.eta)
            shape = shape / max(area, 1e-12)
        out[i0:i1, j] = shape
    return out


def lebail_fit(phases: list[CifStructure], pat: Pattern,
               prm: ProfileParams, cfg, *, max_cycles: int = 30,
               tol: float = 1e-5) -> LeBailResult:
    """Le Bail 迭代拟合：提取逐峰积分强度并返回计算谱。"""
    from xinrefinement.core.refine.nonlinear import RefineConfig

    if isinstance(cfg, RefineConfig):
        tmin, tmax, n_bg, bg_mode = (cfg.tmin, cfg.tmax, cfg.n_bg, cfg.bg_mode)
        sigma = cfg.sigma
    else:
        tmin, tmax = getattr(cfg, "tmin", 5.0), getattr(cfg, "tmax", 90.0)
        n_bg, bg_mode = getattr(cfg, "n_bg", 3), getattr(cfg, "bg_mode", "cheb")
        sigma = getattr(cfg, "sigma", None)

    tt, yo = pat.two_theta, pat.intensity
    sig = (np.sqrt(np.maximum(yo, 1.0)) if sigma is None
           else np.asarray(sigma, dtype=np.float64))
    w = 1.0 / np.maximum(sig ** 2, 1e-12)

    positions = [_peak_positions(s, prm, tmin, tmax) for s in phases]
    shapes = [_profile_matrix(tt, pos + prm.zero, prm) for pos in positions]
    # 初值：结构积分强度按 Kα 权重摊到各峰位（与 _peak_positions 的双线枚举
    # 对齐）；没有结构强度时给常数。列数必须等于 shapes 的列数。
    intensities = []
    for s, pos, sh in zip(phases, positions, shapes):
        from xinrefinement.core.profile.shape import resolve_wavelengths
        comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
        pk, _ = compute_peaks(s, prm.wavelength, tmin, tmax,
                              wavelengths=comps)
        struct_I = np.array([max(p[1], 1e-6) for p in pk], dtype=float)
        if struct_I.size == sh.shape[1]:
            intensities.append(struct_I)
        else:
            # 枚举口径不同时的兜底：全 1（Le Bail 本身不依赖结构初值）
            intensities.append(np.ones(sh.shape[1], dtype=float))

    history: list[float] = []
    ycalc = np.zeros_like(yo)
    coeffs = None
    for cycle in range(max_cycles):
        # 组装：每相的合成谱（列向量）+ 背景基
        rows = [sh @ I for sh, I in zip(shapes, intensities)]
        basis = np.vstack(rows) if rows else np.zeros((0, tt.size))
        # 相标度固定为 1（强度已在 I 里），只解背景
        coeffs, ycalc, _dropped = solve_linear_detail(
            basis, tt, yo, sig, n_bg, bg_mode)
        rwp = compute_rfactors(yo, ycalc,
                               n_params=sum(I.size for I in intensities)
                               + n_bg).rwp
        history.append(rwp)

        # 乘性强度更新（Rietveld 分解）：逐峰在自身窗口内累加
        new_int = []
        for sh, I in zip(shapes, intensities):
            num = (w * yo) @ sh
            den = (w * ycalc) @ sh
            ratio = np.where(den > 0, num / np.maximum(den, 1e-12), 1.0)
            new_int.append(np.maximum(I * ratio, 1e-9))
        intensities = new_int

        if len(history) >= 2 and abs(history[-1] - history[-2]) < tol:
            break

    # 末次用更新后的强度重算谱
    rows = [sh @ I for sh, I in zip(shapes, intensities)]
    basis = np.vstack(rows) if rows else np.zeros((0, tt.size))
    coeffs, ycalc, _ = solve_linear_detail(basis, tt, yo, sig, n_bg, bg_mode)
    rf = compute_rfactors(yo, ycalc,
                          n_params=sum(I.size for I in intensities) + n_bg)
    return LeBailResult(
        rwp=float(rf.rwp), rp=float(rf.rp), rexp=float(rf.rexp),
        chi2=float(rf.chi2),
        intensities=tuple(tuple(float(v) for v in I) for I in intensities),
        positions=tuple(tuple(float(v) for v in p) for p in positions),
        ycalc=np.asarray(ycalc, dtype=float),
        history=tuple(history), cycles=len(history),
        converged=bool(len(history) >= 2
                       and abs(history[-1] - history[-2]) < tol))


def lebail_weights(phases: list[CifStructure], result: LeBailResult,
                   formulas: dict[str, str] | None = None):
    """由提取的逐峰总强度做 Hill–Howard 相定量（与 Rietveld 口径一致）。"""
    from xinrefinement.core.refine.qpa import PhaseWeight, qpa_inputs_from_cif, qpa_weights
    fs = formulas or {}
    totals = [float(np.sum(I)) for I in result.intensities]
    triples = []
    for st, sc in zip(phases, totals):
        z, v, m = qpa_inputs_from_cif(st, fs.get(st.name))
        triples.append((st.name, sc, z, v, m))
    return qpa_weights(triples)
