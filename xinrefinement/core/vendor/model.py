# vendored from PolyXRD-RutAna :: rutana/core/vendor/model.py
"""
复制范围: 完整复制 PolyXRD-Converter src/polyxrd_converter/model.py
（源自 PolyXRD-Converter，© 2026 PolyXRD Team，dual-licensed）。数据模型逻辑未改动。

谱图数据模型
============
只保留格式转换需要的最小字段: 2θ 轴、强度、波长、元数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class XRDData:
    """(2θ, 强度) 谱图。

    Attributes:
        two_theta: 2θ 角度数组 (度), 与 ``intensity`` 等长
        intensity: 强度数组
        wavelength: X 射线波长 (Å); None 表示未知
        metadata: 附加信息 (来源文件、识别出的格式/仪器名等)
    """

    two_theta: np.ndarray
    intensity: np.ndarray
    wavelength: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.two_theta = np.asarray(self.two_theta, dtype=float)
        self.intensity = np.asarray(self.intensity, dtype=float)
        if self.two_theta.shape != self.intensity.shape:
            raise ValueError(
                f"2θ 与强度长度不一致: {self.two_theta.size} vs {self.intensity.size}"
            )

    def __len__(self) -> int:
        return int(self.two_theta.size)

    def copy(self) -> "XRDData":
        return XRDData(
            two_theta=self.two_theta.copy(),
            intensity=self.intensity.copy(),
            wavelength=self.wavelength,
            metadata=dict(self.metadata),
        )

    # ---- 序列化 (供 .json 读写) --------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "two_theta": [float(v) for v in self.two_theta],
            "intensity": [float(v) for v in self.intensity],
            "wavelength": self.wavelength,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "XRDData":
        return cls(
            two_theta=np.asarray(payload["two_theta"], dtype=float),
            intensity=np.asarray(payload["intensity"], dtype=float),
            wavelength=payload.get("wavelength"),
            metadata=dict(payload.get("metadata") or {}),
        )
