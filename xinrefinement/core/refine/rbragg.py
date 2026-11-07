"""Bragg R 因子（T4.1 · 新建，非 vendor）。

RB 与 Rwp 的区别：Rwp 比较**逐点**曲线，RB 比较**每个衍射峰的积分强度**
（I_obs vs I_calc），因此基本不受背景形状与峰宽模型误差的干扰，是
Rietveld 的"结构层面" goodness-of-fit 指标，也是与 GSAS-II 交叉验证的
主口径之一。

本项目的 RB 口径（写入 STD_FREEZE §2）
------------------------------------
1. **扣除背景**：I_obs 与 I_calc 都在 `y − bg` 上积分（背景不参与）。
2. **重叠峰按计算贡献分配**：数据点按"各峰的模型形状 × 计算权重"归一化
   归属，归属比例 frac_p(x) = w_p·s_p(x) / Σ_q w_q·s_q(x)：
   - s_p(x) 为峰 p 的**单位面积**峰形（伪 Voigt，FWHM 由精修参数给出）；
   - w_p 为该峰的计算权重（|F|²·LP，含 PO 权重）。
   实测与计算用**同一套归属权重**积分，保证重叠区不重复计数。
3. `RB = 100·Σ|I_obs − I_calc| / Σ I_obs`（百分数口径，与 rwp/rp/rexp 一致）。

灵敏度说明：归属权重取自**模型形状**，因此实测峰位偏移会造成该峰实测
积分不足 —— RB 对峰位与强度误差都敏感（与 GSAS-II 在 hkl 级分配的做法
量级一致；差异主要为重叠峰的分配细节，GSAS-II 装好后（T8）做交叉比对）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.profile.size_strain import split_fwhm

#: 峰窗口半宽 = max(窗口系数·FWHM, 最小半宽)（度）
WINDOW_FWHM_FACTOR = 1.5
WINDOW_MIN_HALF_DEG = 0.05
#: 伪 Voigt 面积系数（与前向模型同一口径：∫pV = FWHM·(1.06447+0.50633η)/2）
_PV_AREA_COEF = (1.06447, 0.50633)


@dataclass(frozen=True)
class BraggRResult:
    """RB 计算结果（含逐峰明细，供结果卡/报告引用）。"""

    rbragg: float                       # 百分数
    n_peaks: int
    peaks: tuple[tuple[float, float, float], ...]   # (2θ, I_obs, I_calc)

    def as_dict(self) -> dict:
        return {
            "rbragg": round(self.rbragg, 4),
            "n_peaks": self.n_peaks,
            "peaks": [(round(t, 4), round(oi, 2), round(ci, 2))
                      for t, oi, ci in self.peaks],
        }


def profile_fwhm(prm: ProfileParams):
    """由精修参数给出 pos(2θ) -> FWHM(度) 的可调用对象。

    TCH 开启时逐峰 FWHM 由 (ΓG, ΓL) 决定，否则用 Caglioti。
    """
    tch_on = (prm.X != 0.0) or (prm.Y != 0.0)

    def fwhm(pos: float) -> float:
        if tch_on:
            fw, _eta, _fl = split_fwhm(pos, prm.U, prm.V, max(prm.W, 1e-4),
                                        prm.X, prm.Y,
                                        basis=getattr(prm, "width_basis", "tan"),
                                        wavelength=prm.wavelength)
            return max(fw, 1e-4)
        t = math.tan(math.radians(pos) / 2.0)
        return float(math.sqrt(max(prm.U * t * t + prm.V * t + prm.W, 1e-8)))

    return fwhm


def profile_eta(prm: ProfileParams):
    """逐峰 η（TCH 开启时由 (ΓG, ΓL) 决定，否则用固定 eta）。"""
    from xinrefinement.core.profile.size_strain import fwhm_gaussian, tch_eta

    tch_on = (prm.X != 0.0) or (prm.Y != 0.0)

    def eta(pos: float) -> float:
        if tch_on:
            fg = fwhm_gaussian(pos, prm.U, prm.V, max(prm.W, 1e-4),
                               basis=getattr(prm, "width_basis", "tan"),
                               wavelength=prm.wavelength)
            from xinrefinement.core.profile.size_strain import fwhm_lorentz
            fl = fwhm_lorentz(pos, prm.X, prm.Y)
            return tch_eta(fg, fl)
        return float(prm.eta)

    return eta


def collect_peaks(struct: CifStructure, prm: ProfileParams,
                  tmin: float, tmax: float) -> list[tuple[float, float]]:
    """取模型峰列表 [(2θ, 计算权重)]（权重 = |F|²·LP·PO，用于重叠分配）。"""
    from xinrefinement.core.profile.forward import _peaks_with_po

    peaks = _peaks_with_po(prm, struct, tmin, tmax)
    return [(float(p), float(w)) for p, w, _d in peaks]


def bragg_r_factor(two_theta, y_obs, y_calc, bg_curve, peaks, fwhm_func,
                    *, eta_func=None, window_factor: float = WINDOW_FWHM_FACTOR,
                    min_half_deg: float = WINDOW_MIN_HALF_DEG,
                    shape_fn=None) -> BraggRResult:
    """计算 Bragg R 因子。

    参数
    ----
    two_theta : 2θ 网格（度，升序）
    y_obs     : 实测强度（**含背景**）
    y_calc    : 计算强度（**含背景**）
    bg_curve  : 背景曲线（逐点）
    peaks     : [(2θ, 计算权重)]，通常由 `collect_peaks` 得到
    fwhm_func : pos -> FWHM(度)
    eta_func  : pos -> η；None 时统一用 0.5
    shape_fn  : (pos, x_array, fwhm, eta) -> 单位面积峰形；None 时用伪 Voigt
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    yo = np.asarray(y_obs, dtype=np.float64)
    yc = np.asarray(y_calc, dtype=np.float64)
    bg = np.asarray(bg_curve, dtype=np.float64)
    if not (tt.shape == yo.shape == yc.shape == bg.shape) or tt.ndim != 1:
        raise ValueError("two_theta/y_obs/y_calc/bg_curve 必须等长一维")
    if not peaks:
        return BraggRResult(rbragg=0.0, n_peaks=0, peaks=())

    if tt.size > 1:
        step = float(np.median(np.diff(tt)))
    else:
        step = 1.0

    n = len(peaks)
    pos = np.array([p for p, _w in peaks])
    wgt = np.array([w for _p, w in peaks])
    fw = np.array([fwhm_func(p) for p in pos])
    et = (np.array([eta_func(p) for p in pos]) if eta_func is not None
          else np.full(n, 0.5))
    half = np.maximum(window_factor * fw, min_half_deg)

    # 归属权重：每个峰的模型形状在其窗口内展开
    contrib = np.zeros((n, tt.size))
    for k in range(n):
        i0 = int(np.searchsorted(tt, pos[k] - half[k], side="left"))
        i1 = int(np.searchsorted(tt, pos[k] + half[k], side="right"))
        if i1 <= i0:
            continue
        x = tt[i0:i1]
        if shape_fn is not None:
            s = np.asarray(shape_fn(pos[k], x, fw[k], et[k]), dtype=np.float64)
        else:
            from xinrefinement.core.profile.shape import _pv_peak
            s = _pv_peak(x, pos[k], fw[k], et[k])
            area = fw[k] * (_PV_AREA_COEF[0] + _PV_AREA_COEF[1] * et[k]) / 2.0
            s = s / max(area, 1e-12)      # 归一到单位面积
        contrib[k, i0:i1] = wgt[k] * s

    tot = contrib.sum(axis=0)
    mask = tot > 0
    if not mask.any():
        return BraggRResult(rbragg=0.0, n_peaks=0, peaks=())
    frac = np.zeros_like(contrib)
    frac[:, mask] = contrib[:, mask] / tot[mask]

    net_obs = (yo - bg) * step
    net_calc = (yc - bg) * step
    i_obs = frac @ net_obs
    i_calc = frac @ net_calc

    keep = i_obs > 0
    if not keep.any():
        return BraggRResult(rbragg=0.0, n_peaks=0, peaks=())
    num = float(np.sum(np.abs(i_obs[keep] - i_calc[keep])))
    den = float(np.sum(i_obs[keep]))
    rb = 100.0 * num / den if den > 0 else 0.0
    table = tuple((float(pos[k]), float(i_obs[k]), float(i_calc[k]))
                  for k in range(n) if keep[k])
    return BraggRResult(rbragg=rb, n_peaks=int(keep.sum()), peaks=table)
