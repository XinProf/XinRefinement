"""P2.1 · 零点与样品位移精修（Bragg–Brentano 平板几何）。

两种 2θ 偏移的物理来源不同，不能混为一个参数：

- **零点** ``zero``：常值平移，``Δ(2θ) = zero``；
- **样品位移** ``disp``：样品面偏离测角仪轴 s，偏移
  ``Δ(2θ) = −(2s/R)·cosθ·180/π ≈ −disp·cosθ``（θ = 2θ/2），
  随角度增大而减弱 —— 与零点可分离。

实现口径
--------
引擎的 ``compute_phase_profile`` 把峰放在 ``grid`` 上，且 ``prm.zero``
直接加在峰位。为避免改动 P0 前向模型（golden 零风险），本模块在
**求值网格**上施加位移：令 ``eval_grid = t − zero − (−disp·cosθ)``，
则 ``y(t) = f(eval_grid)`` 等价于观测谱在 t 处看到位移后的峰。

独立引擎（同 P1.2/P1.3 策略），只精修 ``(zero, disp)`` 两个参数，
峰形/晶胞固定，用变量投影消掉 scale+背景。
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

ZERO_BOUNDS = (-0.5, 0.5)
DISP_BOUNDS = (-0.5, 0.5)


def shifted_grid(two_theta: np.ndarray, zero: float, disp: float) -> np.ndarray:
    """返回施加零点 + 样品位移后的求值网格。

    ``disp`` 单位度（= 2s/R 换算到度）；观测峰位 = 计算峰位 + zero − disp·cosθ。
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    theta = np.radians(tt / 2.0)
    return tt - zero + disp * np.cos(theta)


@dataclass(frozen=True)
class GeometryRefineResult:
    zero: float
    disp: float
    rwp: float
    success: bool
    history: tuple[float, ...]
    iters: int


def refine_geometry(phases: list[CifStructure], pat: Pattern,
                    prm0: ProfileParams, cfg,
                    backend: str = "lm") -> GeometryRefineResult:
    """独立精修零点和样品位移（变量投影 + LM/scipy-trf）。"""
    from xinrefinement.core.refine.nonlinear import RefineConfig

    if isinstance(cfg, RefineConfig):
        tmin, tmax = cfg.tmin, cfg.tmax
        n_bg, bg_mode = cfg.n_bg, cfg.bg_mode
        sigma, max_iter = cfg.sigma, cfg.max_iter
    else:
        tmin, tmax = getattr(cfg, "tmin", 5.0), getattr(cfg, "tmax", 90.0)
        n_bg, bg_mode = getattr(cfg, "n_bg", 3), getattr(cfg, "bg_mode", "cheb")
        sigma, max_iter = getattr(cfg, "sigma", None), getattr(cfg, "max_iter", 40)

    tt, yo = pat.two_theta, pat.intensity
    sig = (np.sqrt(np.maximum(yo, 1.0)) if sigma is None
           else np.asarray(sigma, dtype=np.float64))
    history: list[float] = []
    # zero 置 0：偏移全部由求值网格承担，避免重复
    base = ProfileParams(**{**prm0.__dict__, "zero": 0.0})

    def residual_fn(x: np.ndarray) -> np.ndarray:
        g = shifted_grid(tt, float(x[0]), float(x[1]))
        rows = [compute_phase_profile(s, g, base, tmin, tmax) for s in phases]
        bp = np.vstack(rows) if rows else np.zeros((0, tt.size))
        _c, ycalc, _d = solve_linear_detail(bp, g, yo, sig, n_bg, bg_mode)
        rwp = compute_rfactors(
            yo, ycalc, n_params=x.size + bp.shape[0] + n_bg).rwp
        history.append(rwp)
        return (yo - ycalc) / sig

    x0 = np.array([0.0, 0.0])
    lo = np.array([ZERO_BOUNDS[0], DISP_BOUNDS[0]])
    hi = np.array([ZERO_BOUNDS[1], DISP_BOUNDS[1]])
    if backend == "scipy":
        from scipy.optimize import least_squares
        sr = least_squares(residual_fn, x0, bounds=(lo, hi), method="trf",
                           max_nfev=2000)
        best, success = sr.x, bool(sr.success)
    else:
        lm = lm_minimize(residual_fn, x0, bounds=(lo, hi), max_iter=max_iter)
        best, success = lm.x, lm.success
    residual_fn(best)
    return GeometryRefineResult(
        zero=float(best[0]), disp=float(best[1]),
        rwp=float(history[-1]), success=bool(success),
        history=tuple(history), iters=len(history))
