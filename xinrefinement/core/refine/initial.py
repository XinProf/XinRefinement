"""P2.10 · 自动初值估算（导入谱图+CIF 后「一键可跑」的前提）。

估算内容
--------
- **背景**：取低分位数（默认 10%）的强度作为背景常数估计，避开衍射峰；
- **标度 scale**：用 (峰值−背景) 与单相计算谱峰值的比值；
- **零点 zero**：最强观测峰与计算谱最强峰的 2θ 差（限幅 ±0.3°）；
- **展宽 W**：由最强峰的半高宽反推 Caglioti 常数项 W（限幅 0.005–0.3°）；
- **背景阶数**：默认 3（真实弯背景用 tent，由齿轮弹窗调）。

输出 ``InitialEstimate``，可直接转成 ``ProfileParams`` / ``RefineConfig``。
估算只求「可收敛的起点」，不追求精确（精修会继续优化）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile


@dataclass(frozen=True)
class InitialEstimate:
    zero: float
    W: float
    U: float
    V: float
    background_level: float
    scale: float
    n_bg: int
    strongest_obs: float
    strongest_calc: float
    notes: tuple[str, ...]


def _half_width(grid: np.ndarray, y: np.ndarray, peak_idx: int,
                base: float) -> float:
    """在峰附近估计半高宽（度）；找不到则回退 0.1°。"""
    half = base + (float(y[peak_idx]) - base) / 2.0
    i = peak_idx
    while i > 0 and y[i] > half:
        i -= 1
    j = peak_idx
    while j < y.size - 1 and y[j] > half:
        j += 1
    w = float(grid[j] - grid[i])
    return w if w > 0 else 0.1


def estimate_initial(pattern: Pattern, phases: list[CifStructure],
                     *, tmin: float = 5.0, tmax: float = 90.0,
                     quantile: float = 0.10,
                     anode: str | None = "Cu") -> InitialEstimate:
    """由谱图与 CIF 估算一组可精修的初值。"""
    tt, y = pattern.two_theta, pattern.intensity
    if tt.size < 10:
        raise ValueError("谱图点数不足，无法估算初值")
    bg_level = float(np.quantile(y, quantile))
    net = np.maximum(y - bg_level, 0.0)

    # 用略尖的试探峰形算计算谱（只是找峰位/峰高，不要求精确）
    probe = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.08, eta=0.5,
                          anode=anode, integrated=False)
    calc = np.zeros_like(tt)
    for st in phases:
        calc += compute_phase_profile(st, tt, probe, tmin, tmax)

    obs_peak = int(np.argmax(net))
    calc_peak = int(np.argmax(calc)) if float(calc.max()) > 0 else obs_peak
    obs_pos, calc_pos = float(tt[obs_peak]), float(tt[calc_peak])
    zero = float(np.clip(obs_pos - calc_pos, -0.3, 0.3))

    fwhm = _half_width(tt, y, obs_peak, bg_level)
    W = float(np.clip(max(fwhm, 0.02) ** 2, 0.005, 0.3))
    calc_max = float(calc.max())
    scale = float(np.clip(net[obs_peak] / calc_max, 1e-6, 1e12)) \
        if calc_max > 0 else 1.0

    notes = (
        f"背景取 {quantile:.0%} 分位数 = {bg_level:.1f}",
        f"最强观测峰 {obs_pos:.3f}° / 计算峰 {calc_pos:.3f}° → zero={zero:+.4f}°",
        f"最强峰半高宽 ≈{fwhm:.3f}° → W={W:.4f}",
    )
    return InitialEstimate(
        zero=zero, W=W, U=0.0, V=0.0,
        background_level=bg_level, scale=scale, n_bg=3,
        strongest_obs=obs_pos, strongest_calc=calc_pos, notes=notes)


def to_profile_params(est: InitialEstimate, anode: str | None = "Cu",
                      integrated: bool = True) -> ProfileParams:
    """把估算值转成精修起点。"""
    return ProfileParams(zero=est.zero, U=est.U, V=est.V, W=est.W,
                         eta=0.5, anode=anode, integrated=integrated)
