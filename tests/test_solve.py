"""M0.1 solve() 契约与数值测试。

覆盖：
1. 现有 virtual_b 双相虚拟样 round-trip（与 P0 golden 同口径）；
2. 单相自洽合成谱 round-trip（前向模型造谱 -> solve 回收峰形真值）；
3. 谱图超出精修窗口时的自动裁剪与 warning。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"


def _two_phase_inputs():
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=3, max_iter=40, tmin=5.0, tmax=90.0)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def test_solve_virtual_b_two_phase_roundtrip():
    """v50 双相虚拟样：Rwp 与 golden(≈3.41%) 同档，含两相且 QPA 可算。"""
    inp = _two_phase_inputs()
    res = solve(inp)
    assert res.success
    assert res.rwp < 5.0
    assert res.ycalc.shape == inp.pattern.intensity.shape
    assert len(res.phases) == 2
    # QPA 用 CIF 自带化学式（内置 rutile CIF 为 O2 Ti0.992），与 bench 显式
    # 教材式 O2 Ti 略有差异；对真值 50% 的回收误差应 < 0.5pp。
    wa = res.phases[0].weight_pct  # anatase
    assert wa is not None and abs(wa - 50.0) < 0.5
    assert res.phases[0].formula is not None


def test_solve_single_phase_linear_exact():
    """单相自洽（线性层）：峰形给定真值、只解 scale+背景，应精确复现。

    说明：本卡不在此处逼 LM 全参数冷启动 —— U/V/W 与 zero 强相关，冷启动
    可能落入 ~7% 的局部极小（QPA 不受影响）；全参数回收由 virtual_b 双相
    round-trip 覆盖（T0.3 已验证引擎）。
    """
    st = parse_cif(DATA_CIF / "anatase.cif")
    grid = np.arange(5.0, 90.0, 0.02)
    truth = ProfileParams(zero=0.05, U=0.02, V=0.0, W=0.02, eta=0.5,
                          anode="Cu", integrated=True)
    phase = compute_phase_profile(st, grid, truth, 5.0, 90.0)
    bg = chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    pat = Pattern(two_theta=grid, intensity=1000.0 * phase + bg)
    cfg = RefineConfig(refine_zero=False, refine_uvw=False, n_bg=3,
                       tmin=5.0, tmax=90.0)
    res = solve(RefineInputs(pattern=pat, phases=[st], profile=truth,
                             config=cfg, formulas={"anatase": "O2 Ti"}))
    assert res.success
    assert res.rwp < 1e-6
    assert res.phases[0].weight_pct == pytest.approx(100.0)


def test_solve_single_phase_zero_recovery():
    """单相自洽（zero 回收）：峰形固定真值，从 zero=0 应回收到真值 0.05°。"""
    st = parse_cif(DATA_CIF / "anatase.cif")
    grid = np.arange(5.0, 90.0, 0.02)
    truth = ProfileParams(zero=0.05, U=0.02, V=0.0, W=0.02, eta=0.5,
                          anode="Cu", integrated=True)
    phase = compute_phase_profile(st, grid, truth, 5.0, 90.0)
    bg = chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    pat = Pattern(two_theta=grid, intensity=1000.0 * phase + bg)
    start = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                          anode="Cu", integrated=True)
    cfg = RefineConfig(refine_zero=True, refine_uvw=False, n_bg=3,
                       tmin=5.0, tmax=90.0)
    res = solve(RefineInputs(pattern=pat, phases=[st], profile=start,
                             config=cfg, formulas={"anatase": "O2 Ti"}))
    assert res.success
    assert res.rwp < 0.5
    assert abs(res.params.zero - 0.05) < 0.005


def test_solve_clips_pattern_to_window():
    """谱图超出 [tmin,tmax] 时自动裁剪并给 warning。"""
    st = parse_cif(DATA_CIF / "anatase.cif")
    grid = np.arange(5.0, 120.0, 0.02)
    truth = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5, anode="Cu")
    phase = compute_phase_profile(st, grid, truth, 5.0, 90.0)
    pat = Pattern(two_theta=grid, intensity=100.0 * phase + 300.0)
    cfg = RefineConfig(refine_zero=False, refine_uvw=True, n_bg=1, max_iter=20,
                       tmin=5.0, tmax=90.0)
    res = solve(RefineInputs(pattern=pat, phases=[st], profile=truth, config=cfg))
    assert res.pattern.two_theta[-1] <= 90.0
    assert any("裁剪" in w for w in res.warnings)


def test_solve_requires_phase():
    inp = _two_phase_inputs()
    with pytest.raises(ValueError):
        solve(RefineInputs(pattern=inp.pattern, phases=[], profile=inp.profile,
                           config=inp.config))
