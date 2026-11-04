"""P1.5 / P2.1 / P2.2 / P3.5 验收。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.diagnostics import diagnose, durbin_watson
from xinrefinement.core.refine.esd import estimate_esd
from xinrefinement.core.refine.geometry import refine_geometry, shifted_grid
from xinrefinement.core.refine.linear import (
    background_basis,
    manual_basis,
    solve_linear_detail,
)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"


def _inputs():
    pat = load_pattern(PATTERN)
    phases = [parse_cif(CIF_A), parse_cif(CIF_R)]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3,
                       tmin=5.0, tmax=90.0, max_iter=40)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


# ---- P1.5 e.s.d. ------------------------------------------------------ #
def test_esd_full_covariance_includes_linear_params():
    """Schur 补必须把 scale/背景纳入：标签含 scale/bg，e.s.d. 全为正。"""
    inp = _inputs()
    res = solve(inp)
    out = estimate_esd(inp.phases, res,
                       formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"})
    assert any(s.startswith("scale[") for s in out.labels)
    assert any(s.startswith("bg[") for s in out.labels)
    assert out.n_params == len(out.labels) == out.covariance.shape[0]
    assert out.n_points == res.pattern.two_theta.size
    assert all(v >= 0 and np.isfinite(v) for v in out.esd)
    assert all(v > 0 for v in out.scale_esd), "scale e.s.d. 不应为零"
    assert out.weight_esd_pct is not None
    assert all(v > 0 for v in out.weight_esd_pct), "含量 e.s.d. 不应为空"
    assert out.variance_factor > 0
    assert np.allclose(np.diag(out.correlation), 1.0, atol=1e-6)


def test_esd_schur_consistency():
    """两条独立路径的 Schur 补应一致（相对差 <5%，验收口径）。"""
    inp = _inputs()
    res = solve(inp)
    out = estimate_esd(inp.phases, res)
    assert out.schur_consistency < 0.05, out.schur_consistency


def test_esd_covariance_symmetric_psd():
    inp = _inputs()
    out = estimate_esd(inp.phases, solve(inp))
    C = out.covariance
    assert np.allclose(C, C.T, atol=1e-8)
    ev = np.linalg.eigvalsh(C)
    assert float(ev.min()) > -1e-6


# ---- P2.1 样品位移 ---------------------------------------------------- #
def test_shifted_grid_angle_dependence():
    """位移偏移随角度衰减（cosθ），零点为常值。"""
    tt = np.array([20.0, 40.0, 60.0, 80.0])
    g = shifted_grid(tt, 0.0, 0.1)
    shifts = tt - g
    assert shifts[0] < 0 and shifts[-1] < 0
    assert shifts[0] < shifts[-1]           # 高角偏移更小
    assert np.allclose(shifted_grid(tt, 0.05, 0.0), tt - 0.05)


def _geom_pattern(phases, zero, disp):
    grid = np.arange(10.0, 90.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    g = shifted_grid(grid, zero, disp)
    y = np.zeros_like(grid)
    for st in phases:
        y += 1000.0 * compute_phase_profile(st, g, prm, 10.0, 90.0)
    from xinrefinement.core.refine.linear import chebyshev_basis
    y += chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    return Pattern(two_theta=grid, intensity=y, meta={}), prm


@pytest.mark.parametrize("zero,disp", [(0.06, 0.0), (0.0, 0.12),
                                      (0.05, -0.10)])
def test_geometry_roundtrip(zero, disp):
    """P2.1 验收：零点/样品位移回收误差 < 0.005°。"""
    st = parse_cif(CIF_A)
    pat, prm = _geom_pattern([st], zero, disp)
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=80)
    res = refine_geometry([st], pat, prm, cfg, backend="scipy")
    assert res.success and res.rwp < 1.0, (res.rwp, res.history[-3:])
    assert abs(res.zero - zero) < 0.005, (res.zero, zero)
    assert abs(res.disp - disp) < 0.005, (res.disp, disp)


# ---- P2.2 手动背景 ---------------------------------------------------- #
def test_manual_basis_interpolation():
    pts = [(10.0, 100.0), (30.0, 300.0), (50.0, 100.0)]
    b = manual_basis(np.array([10.0, 20.0, 30.0, 40.0, 60.0]), pts).ravel()
    assert np.allclose(b, [100.0, 200.0, 300.0, 200.0, 100.0])
    with pytest.raises(ValueError):
        manual_basis(np.array([10.0]), [(10.0, 1.0)])
    # 重复 2θ 无法插值 -> 报错（乱序点会自动排序，属正常拖拽顺序）
    with pytest.raises(ValueError):
        manual_basis(np.array([10.0]), [(10.0, 1.0), (10.0, 2.0)])
    assert manual_basis(np.array([15.0]), [(20.0, 1.0), (10.0, 2.0)]).ravel()[0] \
        == pytest.approx(1.5)


def test_manual_background_solve():
    """manual 固定背景被正确扣除，scale 可解，ycalc 含背景。"""
    grid = np.arange(10.0, 60.0, 0.5)
    p = 2.0 * np.exp(-((grid - 30.0) / 2.0) ** 2)
    pts = [(10.0, 100.0), (60.0, 100.0)]
    y = 5.0 * p + 100.0
    coeffs, ycalc, dropped = solve_linear_detail(
        p[None, :], grid, y, None, n_bg=1, bg_mode="manual", bg_points=pts)
    assert coeffs[0] == pytest.approx(5.0, rel=1e-6)
    assert coeffs[-1] == pytest.approx(1.0)
    assert np.allclose(ycalc, y, atol=1e-8)
    assert dropped == []


def test_background_basis_dispatch():
    assert background_basis(np.arange(10.0, 20.0, 1.0), 3, "cheb").shape == (10, 3)
    assert background_basis(np.arange(10.0, 20.0, 1.0), 4, "tent").shape == (10, 4)
    assert background_basis(np.arange(10.0, 20.0, 1.0), 1, "manual",
                            points=[(10.0, 5.0), (20.0, 5.0)]).shape == (10, 1)
    with pytest.raises(ValueError):
        background_basis(np.arange(10.0, 20.0, 1.0), 3, "manual")


# ---- P3.5 诊断量 ------------------------------------------------------ #
def test_durbin_watson_values():
    assert durbin_watson(np.zeros(10)) != durbin_watson(np.zeros(10))  # nan
    assert durbin_watson(np.array([1.0, 1.0, 1.0, 1.0])) == pytest.approx(0.0)
    assert durbin_watson(np.array([1.0, -1.0, 1.0, -1.0])) == pytest.approx(3.0)


def test_diagnose_from_solve():
    inp = _inputs()
    d = diagnose(solve(inp))
    assert d.rwp_final == pytest.approx(d.rwp_start - d.rwp_drop)
    assert d.n_evals > 0
    assert 0.0 <= d.dw <= 4.0
    assert d.verdict


# ---- TCH 切换边界（X/Y 停在 0）下的 e.s.d. 回归 ----------------------- #
def test_esd_tch_boundary_excluded():
    """X/Y 恰为 0（TCH 分支开关处）时：一致性检查剔除边界列且 < 0.05，
    边界参数 e.s.d. 为 NaN，其余参数 e.s.d. 有限。

    复现路径：配方链 micro 步（refine_po/size/strain 全开）后 LM 把
    X/Y 留在 0 —— 未修复时 Schur 一致性实测 0.36。
    """
    from dataclasses import replace as dreplace

    from xinrefinement.core.refine.recipe import DEFAULT_STEPS, RecipeRunner

    inp = _inputs()
    runner = RecipeRunner()
    res = None
    for step in DEFAULT_STEPS:
        res, rec = runner.run_step(step, inp, res)
        if rec.status == "failed" or res is None:
            pytest.skip(f"配方步骤 {step.key} 未执行成功")
        if step.key == "micro":
            break
    if res.params.X != 0.0 and res.params.Y != 0.0:
        pytest.skip("本数据集 X/Y 未停在 TCH 边界，用例不适用")
    esd = estimate_esd(inp.phases, res)
    assert esd.schur_consistency < 0.05, esd.schur_consistency
    labels = list(esd.labels)
    for lab, v in zip(labels, esd.esd):
        if lab.endswith(".micro.X") or lab.endswith(".micro.Y"):
            assert not np.isfinite(v), (lab, v)
        else:
            assert np.isfinite(v), (lab, v)
    assert all(np.isfinite(e) for e in esd.scale_esd)
