"""T4.1 验收 · 线性层测试：scale+背景恢复 / 负标度剔除。"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.refine.linear import (
    chebyshev_basis,
    solve_linear,
    solve_linear_detail,
)


def _gauss(grid, pos, fwhm):
    return np.exp(-4.0 * np.log(2.0) * ((grid - pos) / fwhm) ** 2)


@pytest.fixture()
def small_grid():
    return np.arange(20.0, 35.0, 0.02)


def test_chebyshev_basis_values():
    x = np.linspace(0.0, 4.0, 5)
    b = chebyshev_basis(x, 3)
    # x 映射到 [-1,1]: T0=1, T1=x', T2=2x'^2-1
    expect_x = 2.0 * (x - x[0]) / (x[-1] - x[0]) - 1.0
    assert np.allclose(b[:, 0], 1.0)
    assert np.allclose(b[:, 1], expect_x)
    assert np.allclose(b[:, 2], 2.0 * expect_x ** 2 - 1.0)


def test_recover_scales_clean(small_grid):
    """S=[3,1]、bg=[500,0,0] 无噪声 -> 相对误差 < 1e-6。"""
    p1 = _gauss(small_grid, 25.3, 0.15)
    p2 = _gauss(small_grid, 27.4, 0.15)
    bg = chebyshev_basis(small_grid, 3)
    y = 3.0 * p1 + 1.0 * p2 + 500.0 * bg[:, 0]
    coeffs, ycalc = solve_linear(np.vstack([p1, p2]), small_grid, y, None, 3)
    assert abs(coeffs[0] - 3.0) / 3.0 < 1e-6
    assert abs(coeffs[1] - 1.0) / 1.0 < 1e-6
    assert abs(coeffs[2] - 500.0) / 500.0 < 1e-6
    assert abs(coeffs[3]) < 1e-6 and abs(coeffs[4]) < 1e-6
    assert np.allclose(ycalc, y, atol=1e-8)


def test_recover_scales_noisy(small_grid):
    """加 1% 高斯噪声（σ = 1%·基峰高）-> 相对误差 < 2%。

    注: 无权重 lstsq 下 S 的估计 std ≈ σ/||p||，噪声取基峰高的 1%（0.01）
    而非含背景谱最大值的 1%，否则窄峰的估计误差天然超过 2%（估计 std ≈ 0.7·S）。
    """
    rng = np.random.default_rng(20260701)
    p1 = _gauss(small_grid, 25.3, 0.15)
    p2 = _gauss(small_grid, 27.4, 0.15)
    bg = chebyshev_basis(small_grid, 3)
    y = 3.0 * p1 + 1.0 * p2 + 500.0 + 0.01 * rng.standard_normal(small_grid.size)
    coeffs, _yc = solve_linear(np.vstack([p1, p2]), small_grid, y, None, 3)
    assert abs(coeffs[0] - 3.0) / 3.0 < 0.02
    assert abs(coeffs[1] - 1.0) / 1.0 < 0.02


def test_negative_scale_dropped(small_grid):
    """隐含负标度的相被剔除重解, scale 置 0 并标记 phase_dropped。

    剔除后 −0.5·p2 的少量泄漏由背景多项式吸收, 故 S1 容差放宽到 1%。
    """
    p1 = _gauss(small_grid, 25.3, 0.15)
    p2 = _gauss(small_grid, 27.4, 0.15)
    y = 3.0 * p1 - 0.5 * p2 + 200.0
    coeffs, _yc, dropped = solve_linear_detail(
        np.vstack([p1, p2]), small_grid, y, None, 3)
    assert 1 in dropped
    assert coeffs[1] == 0.0
    assert coeffs[0] == pytest.approx(3.0, abs=0.03)


def test_sigma_weighting(small_grid):
    """sigma 加权路径可用且不改变无噪结果。"""
    p1 = _gauss(small_grid, 25.3, 0.15)
    p2 = _gauss(small_grid, 27.4, 0.15)
    y = 3.0 * p1 + 1.0 * p2 + 500.0
    sigma = np.sqrt(np.maximum(y, 1.0))
    coeffs, _yc = solve_linear(np.vstack([p1, p2]), small_grid, y, sigma, 3)
    assert abs(coeffs[0] - 3.0) / 3.0 < 1e-6
    assert abs(coeffs[1] - 1.0) / 1.0 < 1e-6
