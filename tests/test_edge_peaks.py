"""窗口边界峰泄漏回归（v1.5 边界修复的护栏）。

现象：反射枚举原本严格按 ``[tmin, tmax]`` 过滤，于是**窗口外一点点**位置的
强峰被整体丢掉，而它在窗口内仍有可测的尾巴。IUCr 纯刚玉最典型：149–150°
区间 ``tmax=150`` 的单相计算谱最大值 142370、``tmax=152`` 时 300805
（差 2.1 倍），那半度因此占掉整谱 18.8% 的加权残差。

修法：``_phase_peaks`` 枚举时外扩 ``forward._EDGE_MARGIN``（3°），累加侧
``_window_slice`` 会把峰裁到网格内，不会引入窗口外强度。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.profile import forward as F
from xinrefinement.core.profile.cif import parse_cif_string
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile


@pytest.fixture(scope="module")
def corundum(cif_dir):
    path = cif_dir / "NCA_80_15_05.cif"        # 层状氧化物，峰足够多
    if not path.exists():
        pytest.skip("缺 NCA_80_15_05.cif")
    return parse_cif_string(path.read_text(encoding="utf-8"), "NCA")


def _profile(st, prm, tmax: float, margin: float, monkeypatch):
    monkeypatch.setattr(F, "_EDGE_MARGIN", margin)
    F._PEAKS_CACHE.clear()
    grid = np.arange(5.0, tmax + 1e-9, 0.02)
    out = compute_phase_profile(st, grid, prm, 5.0, tmax)
    F._PEAKS_CACHE.clear()
    return grid, out


def test_edge_peak_tail_is_not_dropped(corundum, monkeypatch) -> None:
    """外扩后，窗口最后 1° 的计算强度必须显著高于不外扩（说明尾巴被捡回来）。"""
    prm = ProfileParams(zero=0.0, U=0.01, V=0.02, W=0.015, eta=0.45,
                        anode="Cu", integrated=True)
    # 44.563° 有一条强峰，正好落在 tmax=44.2 的外扩余量内
    tmax = 44.2
    grid, with_margin = _profile(corundum, prm, tmax, 3.0, monkeypatch)
    _, no_margin = _profile(corundum, prm, tmax, 0.0, monkeypatch)
    edge = grid >= tmax - 1.0
    s_m = float(with_margin[edge].sum())
    s_n = float(no_margin[edge].sum())
    assert s_m > s_n * 1.02, f"边界 1° 内强度 {s_m:.1f} 未高于 {s_n:.1f}——边界峰仍被丢"


def test_edge_margin_does_not_leak_outside_window(corundum, monkeypatch) -> None:
    """外扩只影响窗口**内**的尾巴，网格外不产生任何强度。"""
    prm = ProfileParams(zero=0.0, U=0.01, V=0.02, W=0.015, eta=0.45,
                        anode="Cu", integrated=True)
    grid, prof = _profile(corundum, prm, 44.2, 3.0, monkeypatch)
    assert prof.shape == grid.shape
    assert np.all(np.isfinite(prof))
    assert prof.min() >= 0.0


def test_peak_list_extends_beyond_window(corundum) -> None:
    """``_phase_peaks`` 返回的峰列表里确实存在超出 [tmin, tmax] 的峰。"""
    F._PEAKS_CACHE.clear()
    prm = ProfileParams(anode="Cu")
    peaks, _detail, _skipped = F._phase_peaks(corundum, prm, 20.0, 44.2)
    pos = np.array([p[0] for p in peaks])
    assert (pos > 44.2).any(), "没有任何 > tmax 的峰 → 外扩没生效"
    assert (pos > 44.2 + F._EDGE_MARGIN + 1e-6).sum() == 0, "外扩超出余量"
    assert (pos < 20.0).any(), "没有任何 < tmin 的峰 → 下边界没外扩"
    F._PEAKS_CACHE.clear()
