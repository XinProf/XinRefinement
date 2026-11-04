"""P3.5 / §8.9 · 拟合诊断量（core 层，GUI 与报告共用）。

- Durbin–Watson 统计量：残差一阶自相关，检视背景/峰形模型欠拟合
  （DW≈2 无自相关，<1.5 提示系统性欠拟合）；
- 收敛摘要：Rwp 历史、总下降、是否停滞；
- 高相关参数对：由 e.s.d. 协方差给出（P1.5 结果）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.refine.solve import SolveResult


def durbin_watson(residual) -> float:
    """残差一阶自相关统计量 ``Σ(Δr)² / Σ r²``。"""
    r = np.asarray(residual, dtype=np.float64).ravel()
    if r.size < 2:
        return float("nan")
    denom = float(r @ r)
    if denom <= 0:
        return float("nan")
    d = np.diff(r)
    return float(d @ d) / denom


@dataclass(frozen=True)
class FitDiagnostics:
    dw: float
    rwp_start: float
    rwp_final: float
    rwp_drop: float
    stalled: bool
    n_evals: int
    residual_rms: float
    verdict: str


def diagnose(res: SolveResult, stall_tol: float = 1e-3) -> FitDiagnostics:
    """由一次精修结果汇总诊断量。"""
    hist = np.asarray(res.history, dtype=float)
    start = float(hist[0]) if hist.size else res.rwp
    final = float(res.rwp)
    residual = res.pattern.intensity - res.ycalc
    dw = durbin_watson(residual)
    stalled = bool(hist.size >= 3
                   and abs(float(hist[-1]) - float(hist[-3])) < stall_tol)
    rms = float(np.sqrt(np.mean(residual ** 2)))
    if math.isnan(dw):
        verdict = "残差为零（无噪声数据）"
    elif dw < 1.5:
        verdict = "残差存在正自相关，背景/峰形可能欠拟合"
    elif dw > 2.5:
        verdict = "残差存在负自相关，检查权重方案"
    else:
        verdict = "残差无明显自相关"
    return FitDiagnostics(
        dw=dw, rwp_start=start, rwp_final=final,
        rwp_drop=start - final, stalled=stalled, n_evals=int(hist.size),
        residual_rms=rms, verdict=verdict)
