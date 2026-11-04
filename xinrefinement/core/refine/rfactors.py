# vendored from PolyXRD-RutAna :: rutana/core/refine/rfactors.py
"""B 法精修 · R 因子（T4.2）。

口径说明（GSAS-II / Rietveld 通用口径）：
- 权重 w_i = 1/σ_i²，σ 缺省按计数统计 σ_i = √max(y_obs_i, 1)。
- **背景计入**（GSAS-II 口径）：Σ 与分母对全部数据点求和，拟合的背景包含在
  y_calc 内。FullProf 等软件另有"背景不计入"变体（先扣背景再算）；本模块的
  include_bg=False 表示调用方已从 y_obs / y_calc 中扣除背景后再传入，
  本函数按传入数组原样计算，用于与 FullProf 口径交叉比对。
- Rexp 同样以百分数给出：Rexp = 100·√((N−P)/Σ w·y_o²)，χ² = (Rwp/Rexp)²。
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass


@dataclass(frozen=True)
class RFactors:
    """Rietveld 拟合优度因子（百分数口径，rbragg 留待 T4.6 之后）。"""

    rwp: float
    rp: float
    rexp: float
    chi2: float
    rbragg: float | None = None


def compute_rfactors(yobs, ycalc, *, n_params: int,
                     sigma: np.ndarray | None = None,
                     include_bg: bool = True) -> RFactors:
    """计算 Rwp / Rp / Rexp / χ²。

    yobs, ycalc : 等长观测/计算强度数组
    n_params    : 可调参数总数 P（用于 Rexp）
    sigma       : 每点 σ；None -> √max(y_obs, 1)（计数统计）
    include_bg  : True = GSAS-II 口径（背景计入）；False = 调用方已扣背景
    分母 Σ w·y_o² 为 0 时抛 ValueError。
    """
    yo = np.asarray(yobs, dtype=np.float64)
    yc = np.asarray(ycalc, dtype=np.float64)
    if yo.shape != yc.shape or yo.ndim != 1 or yo.size == 0:
        raise ValueError("yobs 与 ycalc 必须是等长的一维非空数组")
    if sigma is None:
        sig = np.sqrt(np.maximum(yo, 1.0))
    else:
        sig = np.asarray(sigma, dtype=np.float64)
    w = 1.0 / (sig * sig)

    denom = float(np.sum(w * yo * yo))
    if denom <= 0.0:
        raise ValueError("Σw·y_o² 为 0，无法计算 R 因子")
    diff = yo - yc
    rwp = 100.0 * np.sqrt(float(np.sum(w * diff * diff)) / denom)
    s_obs = float(np.sum(yo))
    if s_obs == 0.0:
        raise ValueError("Σy_o 为 0，无法计算 Rp")
    rp = 100.0 * float(np.sum(np.abs(diff))) / s_obs
    n = yo.size
    p = max(int(n_params), 1)
    rexp = 100.0 * np.sqrt(max(n - p, 1) / denom)
    chi2 = (rwp / rexp) ** 2 if rexp > 0 else float("inf")
    return RFactors(rwp=float(rwp), rp=float(rp), rexp=float(rexp),
                    chi2=float(chi2), rbragg=None)
