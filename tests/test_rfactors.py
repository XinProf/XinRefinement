"""T4.2 验收 · R 因子测试：零失配 / 半高 / 分母为零 / χ² 一致性。"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.refine.rfactors import compute_rfactors


def test_perfect_fit_zero_rwp():
    rng = np.random.default_rng(20260701)
    y = np.abs(rng.standard_normal(500)) * 100 + 200
    rf = compute_rfactors(y, y.copy(), n_params=5)
    assert rf.rwp == pytest.approx(0.0, abs=1e-9)
    assert rf.rp == pytest.approx(0.0, abs=1e-9)


def test_half_height_rwp_50():
    rng = np.random.default_rng(20260701)
    y = np.abs(rng.standard_normal(500)) * 100 + 200
    rf = compute_rfactors(y, 0.5 * y, n_params=5)
    # Rwp = 100·sqrt(Σw(0.5y)²/Σw·y²) = 50（与 sigma 取法无关, 只要加权一致）
    assert rf.rwp == pytest.approx(50.0, abs=0.01)


def test_zero_denominator_raises():
    y = np.zeros(10)
    with pytest.raises(ValueError):
        compute_rfactors(y, y.copy(), n_params=2)


def test_rexp_chi2_consistency():
    rng = np.random.default_rng(20260701)
    y = np.abs(rng.standard_normal(1000)) * 50 + 300
    yc = y + rng.standard_normal(1000) * 10
    rf = compute_rfactors(y, yc, n_params=7)
    assert rf.rexp > 0
    assert rf.chi2 == pytest.approx((rf.rwp / rf.rexp) ** 2, rel=1e-9)
    # N−P 惩罚: Rexp 应随参数增多而略减（(N−P) 变小）
    rf2 = compute_rfactors(y, yc, n_params=30)
    assert rf2.rexp < rf.rexp


def test_rbragg_none():
    y = np.ones(50) * 100.0
    rf = compute_rfactors(y, y + 1.0, n_params=3)
    assert rf.rbragg is None
