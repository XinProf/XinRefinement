# vendored from PolyXRD-RutAna :: rutana/core/dtypes.py
"""核心数据类型 —— 全项目共享契约（T0.3）。

本文件是并行开发的接口契约桩：
- 所有子模块只允许 `from xinrefinement.core.dtypes import ...`，不允许复制定义。
- 修改字段/签名必须另开任务卡，禁止顺手改。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Pattern:
    """一份 XRD 谱图（2θ 升序、等长、float64）。"""

    two_theta: np.ndarray
    intensity: np.ndarray
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        tt = np.asarray(self.two_theta, dtype=np.float64)
        ii = np.asarray(self.intensity, dtype=np.float64)
        if tt.ndim != 1 or ii.ndim != 1:
            raise ValueError("two_theta / intensity 必须是一维数组")
        if tt.size == 0:
            raise ValueError("谱图为空")
        if tt.size != ii.size:
            raise ValueError(f"two_theta 与 intensity 长度不等: {tt.size} vs {ii.size}")
        if tt.size > 1 and not bool(np.all(np.diff(tt) > 0)):
            raise ValueError("two_theta 必须严格升序")
        object.__setattr__(self, "two_theta", tt)
        object.__setattr__(self, "intensity", ii)

    @property
    def step(self) -> float:
        """中位数步长（度）。"""
        if self.two_theta.size < 2:
            raise ValueError("谱图点数不足，无法估计步长")
        return float(np.median(np.diff(self.two_theta)))


@dataclass(frozen=True)
class PeakMeasure:
    """单峰测量结果（净峰高 / 净峰面积 / QA）。"""

    two_theta_at_max: float
    net_height: float
    net_area: float
    background_at_max: float
    fwhm: float
    snr: float
    ok: bool
    message: str
