"""P2.6 / P2.10 / P4.1 验收。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.initial import estimate_initial, to_profile_params
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.micro import (
    microstructure,
    resolve_wavelength,
    roundtrip_check,
    synth_terms,
)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve
from xinrefinement.core.report import export_report

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


# ---- P2.6 微结构 ------------------------------------------------------ #
@pytest.mark.parametrize("size,strain", [(100.0, 1e-4), (500.0, 2e-3),
                                        (30.0, 5e-4)])
def test_micro_roundtrip(size, strain):
    """D / ε 正反演误差 < 5%。"""
    lam = 1.54056
    de, ee = roundtrip_check(size, strain, lam)
    assert de < 0.05 and ee < 0.05


def test_microstructure_output():
    X, Y = synth_terms(200.0, 1e-3, 1.54056)
    prm = ProfileParams(X=X, Y=Y, anode="Cu")
    out = microstructure(prm)
    assert out.size_angstrom == pytest.approx(200.0, rel=1e-6)
    assert out.size_nm == pytest.approx(20.0, rel=1e-6)
    assert out.strain == pytest.approx(1e-3, rel=1e-6)
    assert out.strain_pct == pytest.approx(0.1, rel=1e-6)
    assert "相干衍射畴" in out.note


def test_microstructure_zero_means_not_detected():
    out = microstructure(ProfileParams(X=0.0, Y=0.0))
    assert out.size_angstrom is None and out.size_nm is None
    assert "超出检出上限" in out.note
    assert out.strain == 0.0


def test_resolve_wavelength():
    assert resolve_wavelength(ProfileParams(anode=None, wavelength=1.2)) == 1.2
    assert resolve_wavelength(ProfileParams(anode="Cu")) == pytest.approx(1.54056)


# ---- P2.10 自动初值 --------------------------------------------------- #
def test_initial_estimate_basic():
    inp = _inputs()
    est = estimate_initial(inp.pattern, inp.phases)
    assert 0.005 <= est.W <= 0.3
    assert -0.3 <= est.zero <= 0.3
    assert est.background_level > 0
    assert est.scale > 0
    assert est.n_bg == 3
    assert len(est.notes) == 3


def test_initial_estimate_recovers_zero():
    """合成已知 zero 的谱，估算值应接近真值（限幅内）。"""
    st = parse_cif(CIF_A)
    grid = np.arange(10.0, 90.0, 0.02)
    # 零点只在求值网格侧施加一次（compute_phase_profile 内部还会加 prm.zero）
    truth = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                          anode="Cu", integrated=True)
    g = grid - 0.08
    y = 1000.0 * compute_phase_profile(st, g, truth, 10.0, 90.0)
    y += chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    pat = Pattern(two_theta=grid, intensity=y, meta={})
    est = estimate_initial(pat, [st])
    assert abs(est.zero - 0.08) < 0.05, est.zero


def test_initial_to_profile_params():
    inp = _inputs()
    est = estimate_initial(inp.pattern, inp.phases)
    prm = to_profile_params(est)
    assert prm.zero == est.zero and prm.W == est.W
    assert prm.U == 0.0 and prm.V == 0.0


def test_initial_enables_convergence():
    """P2.10 验收：用估算初值一键精修可收敛到阈值内。"""
    inp = _inputs()
    est = estimate_initial(inp.pattern, inp.phases)
    prm = ProfileParams(zero=est.zero, U=0.0, V=0.0, W=est.W, eta=0.5,
                        anode="Cu", integrated=False)
    res = solve(RefineInputs(pattern=inp.pattern, phases=inp.phases,
                             profile=prm, config=inp.config))
    assert res.success
    assert res.rwp < 10.0, res.rwp


# ---- P4.1 报告导出 ---------------------------------------------------- #
def test_export_report_files(tmp_path):
    inp = _inputs()
    res = solve(inp)
    paths = export_report(res, tmp_path, stem="r")
    assert set(paths) == {"html", "png", "json"}
    for p in paths.values():
        assert Path(p).exists() and Path(p).stat().st_size > 0
    html_text = Path(paths["html"]).read_text(encoding="utf-8")
    assert "Rwp" in html_text and "Durbin-Watson" in html_text
    assert "anatase" in html_text and "rutile" in html_text
    assert "fit" not in html_text[:30]  # 基本结构检查
    assert "<img" in html_text


def test_export_log_is_reproducible(tmp_path):
    inp = _inputs()
    res = solve(inp)
    paths = export_report(res, tmp_path, stem="log")
    log = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert log["r_factors"]["rwp"] == pytest.approx(res.rwp)
    assert len(log["rwp_history"]) == len(res.history)
    assert log["parameters"]["zero"] == pytest.approx(res.params.zero)
    assert len(log["phases"]) == 2
    assert "dw" in log["diagnostics"]
    assert "warnings" in log


def test_export_with_esd(tmp_path):
    from xinrefinement.core.refine.esd import estimate_esd
    inp = _inputs()
    res = solve(inp)
    esd = estimate_esd(inp.phases, res,
                       formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"})
    paths = export_report(res, tmp_path, stem="esd", esd=esd)
    log = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert log["esd"] is not None
    assert len(log["esd"]["labels"]) == esd.n_params
    assert "物相含量 e.s.d." in Path(paths["html"]).read_text(encoding="utf-8")
