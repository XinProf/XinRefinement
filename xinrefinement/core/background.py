# vendored from PolyXRD-RutAna :: rutana/core/background.py
"""A 法背景估计（T2.1 / v1.0.0 扩展）。

三种模式，默认 ``linear_edges``（真实数据实证最优，见下）：

* ``linear_edges``：两端各 edge_frac 比例点取中位数（抗离群）后连直线。
* ``poly``        ：对两端边缘点做 poly_deg 次幂基最小二乘拟合。
* ``chebyshev``   ：对两端边缘点做 poly_deg 次 Chebyshev 基最小二乘拟合
                    （数值条件数优于幂基，阶数 >=3 时推荐，v1.0.0 新增）。

v1.0.0 实证（岛津 TiO2 数据集，6 标样校准 R² 与 8/18/36% 预测误差）：
背景窗必须**越过峰尾**才能无偏。积分窗 ±0.25°/±1.05° 配背景边缘 +0.18°
（即背景窗 ±0.43°/±1.23°）时线性度最好（R²=0.99861、截距 −0.07）；
把背景窗压到峰尾以内会把「背景」抬高并随峰高变化，引入系统性偏差
（同为 ±0.25° 积分窗时，背景边缘 0.15°→0.10° 会让预测误差从 ~2% 恶化到 ~5%）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern

# 支持的背景模式
BG_MODES = ("linear_edges", "poly", "chebyshev")


@dataclass(frozen=True)
class BgConfig:
    """背景估计配置。mode: linear_edges | poly | chebyshev。"""

    mode: str = "linear_edges"
    edge_frac: float = 0.10
    poly_deg: int = 1


def _edge_count(n: int, edge_frac: float) -> int:
    """每侧边缘点数（至少 2 点，至多 n//2）。"""
    k = max(2, int(round(n * edge_frac)))
    return min(k, n // 2)


def _edge_points(p: Pattern, cfg: BgConfig) -> tuple[np.ndarray, np.ndarray]:
    """取两端边缘点的 (x, y)。"""
    tt = p.two_theta
    ii = p.intensity
    k = _edge_count(tt.size, cfg.edge_frac)
    return (np.concatenate([tt[:k], tt[-k:]]),
            np.concatenate([ii[:k], ii[-k:]]))


def estimate_background(p: Pattern, cfg: BgConfig) -> np.ndarray:
    """估计与输入等长的背景曲线。允许出现负值（不裁剪）。

    linear_edges: 两端各 edge_frac 比例点取中位数（抗离群）后连直线。
    poly:         对两端边缘点做 poly_deg 次幂基最小二乘拟合（>=2 阶需 >=4 点）。
    chebyshev:    同上但用 Chebyshev 基（数值更稳，>=3 阶推荐）。
    """
    tt = p.two_theta
    ii = p.intensity
    n = tt.size
    k = _edge_count(n, cfg.edge_frac)
    if cfg.mode == "linear_edges":
        xl = float(np.median(tt[:k]))
        xr = float(np.median(tt[-k:]))
        yl = float(np.median(ii[:k]))
        yr = float(np.median(ii[-k:]))
        if xr <= xl:
            return np.full(n, yl, dtype=np.float64)
        slope = (yr - yl) / (xr - xl)
        return yl + slope * (tt - xl)
    if cfg.mode in ("poly", "chebyshev"):
        deg = int(cfg.poly_deg)
        if deg < 1:
            raise ValueError("poly_deg 至少为 1")
        xs, ys = _edge_points(p, cfg)
        if deg >= 2 and xs.size < 4:
            raise ValueError(">=2 阶多项式背景至少需要 4 个边缘点")
        if cfg.mode == "poly":
            coeffs = np.polyfit(xs, ys, deg)
            return np.polyval(coeffs, tt)
        # Chebyshev：先在 [xmin, xmax] 归一化到 [-1, 1] 再拟合，条件数最优
        xmin, xmax = float(xs.min()), float(xs.max())
        if xmax <= xmin:
            return np.full(n, float(ys.mean()), dtype=np.float64)
        u = (xs - xmin) / (xmax - xmin) * 2.0 - 1.0
        uu = (tt - xmin) / (xmax - xmin) * 2.0 - 1.0
        a = np.polynomial.chebyshev.chebfit(u, ys, deg)
        return np.polynomial.chebyshev.chebval(uu, a)
    raise ValueError(f"未知背景模式: {cfg.mode}（可选: {BG_MODES}）")
