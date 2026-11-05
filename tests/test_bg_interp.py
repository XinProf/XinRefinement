"""v1.2.0 · 插值背景（bg_mode="interp"）与手动背景接线验收。

覆盖：
- ``interp_background_nodes``：合成谱（已知背景 + 峰）上锚点回收；
- ``solve`` 端到端：interp 一次性提取并归一化为 manual，固定背景进 ycalc；
- ``bg_mode="manual"`` 经 RefineConfig.bg_points 真正进引擎（P2.2 断线修复）；
- ``adaptive_n_bg`` 与 CLI 点列解析。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.linear import (
    adaptive_n_bg,
    background_basis,
    interp_background_nodes,
)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"


def _synthetic():
    """已知背景（500→100 线性降）+ 尖峰群的谱，返回 (grid, y, true_bkg)。"""
    st = parse_cif(DATA_CIF / "anatase.cif")
    grid = np.linspace(5.0, 85.0, 1600)
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.04, eta=0.6,
                        anode="Cu", integrated=True)
    peaks = compute_phase_profile(st, grid, prm, 5.0, 85.0)
    true_bkg = 500.0 - 400.0 * (grid - 5.0) / 80.0
    rng = np.random.default_rng(42)
    y = true_bkg + 50.0 * peaks / peaks.max() + rng.normal(0, 3.0, grid.size)
    return grid, np.maximum(y, 1.0), true_bkg


def test_interp_nodes_recover_background():
    grid, y, true_bkg = _synthetic()
    pts = interp_background_nodes(grid, y, n_nodes=8, iterations=10)
    assert len(pts) == 8
    xs = np.array([p[0] for p in pts])
    assert np.all(np.diff(xs) > 0)
    got = np.interp(grid, xs, np.array([p[1] for p in pts]))
    err = np.abs(got - true_bkg)
    tol = 0.05 * (true_bkg.max() - true_bkg.min()) + 10.0
    assert np.percentile(err, 90) < tol, (
        f"锚点回收偏差过大: p90={np.percentile(err, 90):.1f} tol={tol:.1f}")


def test_solve_interp_mode_end_to_end():
    pat_data = load_pattern(ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=8,
                       bg_mode="interp", max_iter=40, tmin=5.0, tmax=90.0)
    res = solve(RefineInputs(pat_data, phases, prm, cfg))
    assert res.success and np.isfinite(res.rwp)
    # bg_mode 保持 interp，锚点写回 bg_points（一次性提取）
    assert res.config.bg_mode == "interp"
    assert len(res.config.bg_points) == 8
    assert any("插值背景" in w for w in res.warnings)
    # 两层可加：interp（固定层 + 自由 cheb）应不劣于同锚点纯固定（manual）
    man_cfg = RefineConfig(**{**cfg.__dict__,
                              "bg_mode": "manual",
                              "bg_points": res.config.bg_points})
    man = solve(RefineInputs(pat_data, phases, prm, man_cfg))
    assert res.rwp <= man.rwp + 1e-9


def test_manual_bg_points_reach_engine():
    """P2.2 断线修复：RefineConfig.bg_points 必须真正进 solve 的线性层。"""
    pat_data = load_pattern(ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    base_cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3,
                            max_iter=40, tmin=5.0, tmax=90.0)
    base = solve(RefineInputs(pat_data, phases, prm, base_cfg))

    # 从 base 拟合谱的背景曲线上取 4 个位置的值当锚点（合理的手动背景）
    tt = base.pattern.two_theta
    sel = [10.0, 30.0, 60.0, 85.0]
    bg_curve = (background_basis(tt, base_cfg.n_bg, base_cfg.bg_mode)
                @ np.asarray(base.background, dtype=float))
    pts = tuple((float(x), float(np.interp(x, tt, bg_curve))) for x in sel)
    man_cfg = RefineConfig(**{**base_cfg.__dict__,
                              "bg_mode": "manual", "bg_points": pts})
    man = solve(RefineInputs(pat_data, phases, prm, man_cfg))
    assert man.config.bg_mode == "manual"
    assert np.isfinite(man.rwp) and man.success
    # 锚点取自计算谱背景 → 拟合质量应与自由背景同档（< 2 点差）
    assert abs(man.rwp - base.rwp) < 2.0


def test_adaptive_n_bg():
    assert adaptive_n_bg(5.0, 90.0) == 14      # 85/6 = 14.2
    assert adaptive_n_bg(5.0, 120.0) == 19     # 115/6 = 19.2
    assert adaptive_n_bg(10.0, 20.0) == 6      # 下限保护
    assert adaptive_n_bg(5.0, 400.0) == 30     # 上限保护
    assert adaptive_n_bg(5.0, 5.0) == 6        # 退化窗口


def test_cli_bg_points_parse():
    from xinrefinement.cli.refine import _parse_bg_points
    assert _parse_bg_points("15:320,60:180") == ((15.0, 320.0), (60.0, 180.0))
    assert _parse_bg_points("") == ()
    with pytest.raises(SystemExit):
        _parse_bg_points("15:320")
