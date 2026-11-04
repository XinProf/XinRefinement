# vendored from PolyXRD-RutAna :: rutana/core/kalpha2.py
"""Kα2 剥离（Rachinger 迭代法）—— v1.0.0 新增（T-A2）。

背景：岛津应用数据集 XRD-019 的实测谱由 Cu Kα 双线（Kα1 1.540598 Å /
Kα2 1.544390 Å）激发，每个 Kα1 峰的"高角侧"都伴随一个强度约为其一半的
Kα2 卫星峰。若不剥离，"最强峰净强度"就会被 Kα2 尾巴污染，且锐钛矿 (101)
与金红石 (110) 受污染的比例不同，直接引入 K 值偏差。

Rachinger 关系（等步长网格上的迭代形式）：
    I_α1(x) = I_obs(x) − r · I_α1(x − Δ2θ(x))
其中 Δ2θ 由 Bragg 方程逐点换算：
    d        = λ1 / (2·sin(2θ/2))
    Δ2θ(2θ)  = 2·[arcsin(λ2/(2d)) − arcsin(λ1/(2d))]
             = 2·arcsin(λ2/(2d)) − 2θ
迭代 k 次等价于展开到 r^k 阶，r=0.5 时 8 次迭代残差已 < 0.4%。

实证结论（见 docs/VALIDATION_v1.0.0.md 与 tools/verify_realdata.py）：
岛津本机已用石墨单色器大幅削弱 Kα2，本数据集上剥离与否对校准 R² 与
预测误差的影响在 ±0.1 pp 量级，因此**默认关闭**（enabled=False），
保留开关供无单色器的老仪器数据使用。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern

# Cu Kα 双线波长（Å），国际表值
LAMBDA_KA1_CU = 1.540598
LAMBDA_KA2_CU = 1.544390

# 常见靶材 Kα 双线波长表（Å），供非 Cu 靶使用
ANODE_WAVELENGTHS: dict[str, tuple[float, float]] = {
    "Cu": (LAMBDA_KA1_CU, LAMBDA_KA2_CU),
    "Co": (1.790260, 1.792850),
    "Fe": (1.936042, 1.939980),
    "Cr": (2.289700, 2.293606),
    "Mo": (0.709300, 0.713590),
}


@dataclass(frozen=True)
class KAlpha2Config:
    """Kα2 剥离配置。

    enabled : 是否剥离。默认 False（岛津数据集实证无需剥离，见模块 docstring）。
    ratio   : Kα2/Kα1 强度比 r，理论 0.5，实测仪器多在 0.45~0.55。
    anode   : 靶材代号，决定 λ1/λ2；未知时抛 ValueError。
    iters   : Rachinger 迭代次数（8 次足够收敛到 <0.4%）。
    """

    enabled: bool = False
    ratio: float = 0.5
    anode: str = "Cu"
    iters: int = 8


def delta_2theta(two_theta_deg: np.ndarray, anode: str = "Cu") -> np.ndarray:
    """逐点计算 Kα2 相对 Kα1 的 2θ 偏移 Δ2θ（度，正值=向高角偏移）。

    公式：d = λ1/(2 sin θ)，θ = 2θ/2；Δ2θ = 2·arcsin(λ2/(2d)) − 2θ。
    """
    if anode not in ANODE_WAVELENGTHS:
        raise ValueError(f"未知靶材: {anode}（可用: "
                         f"{sorted(ANODE_WAVELENGTHS)}）")
    lam1, lam2 = ANODE_WAVELENGTHS[anode]
    tt = np.asarray(two_theta_deg, dtype=np.float64)
    theta = np.deg2rad(tt) / 2.0              # 布拉格角 θ（弧度）
    sin_t = np.clip(np.sin(theta), 1e-9, None)
    d = lam1 / (2.0 * sin_t)                  # 对应晶面间距 d（Å）
    arg = np.clip(lam2 / (2.0 * d), -1.0, 1.0)
    return np.rad2deg(2.0 * np.arcsin(arg)) - tt


def _shift_interp(x: np.ndarray, y: np.ndarray,
                  shift: np.ndarray) -> np.ndarray:
    """返回 y 在 (x − shift) 处的线性插值；超出左边界取 0（无 Kα2 来源）。"""
    target = x - shift
    out = np.interp(target, x, y, left=0.0, right=0.0)
    below = target < x[0]
    out = np.where(below, 0.0, out)
    return out


def strip_kalpha2(p: Pattern,
                  cfg: KAlpha2Config = KAlpha2Config()) -> Pattern:
    """对谱图做 Rachinger Kα2 剥离，返回只含 Kα1 分量的新 Pattern。

    - cfg.enabled=False 时返回原谱副本（行为与 v0.1.0 完全一致）；
    - 非等步长网格也支持（用线性插值按 Δ2θ 逐点取值）；
    - 剥离后不做负值裁剪（负值信息对背景估计有用）。
    """
    tt = p.two_theta
    obs = np.asarray(p.intensity, dtype=np.float64)
    if not cfg.enabled:
        return Pattern(two_theta=tt.copy(), intensity=obs.copy(),
                       meta=dict(p.meta))
    if not 0.0 <= cfg.ratio < 1.0:
        raise ValueError(f"Kα2 强度比 r 必须落在 [0, 1)，收到 {cfg.ratio}")
    if tt.size < 3:
        return Pattern(two_theta=tt.copy(), intensity=obs.copy(),
                       meta=dict(p.meta))
    shift = delta_2theta(tt, cfg.anode)
    cur = obs.copy()
    for _ in range(max(1, int(cfg.iters))):
        cur = obs - cfg.ratio * _shift_interp(tt, cur, shift)
    meta = dict(p.meta)
    meta["kalpha2_stripped"] = True
    meta["kalpha2_ratio"] = float(cfg.ratio)
    meta["kalpha2_anode"] = cfg.anode
    return Pattern(two_theta=tt.copy(), intensity=cur, meta=meta)
