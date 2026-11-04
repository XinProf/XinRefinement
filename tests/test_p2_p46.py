"""P2.3/2.4/2.5/2.7/2.8/2.9 与 P4.6 验收。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from xinrefinement import api
from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif, parse_cif_string
from xinrefinement.core.profile.cif_writer import roundtrip_consistent, write_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.profile.shape import resolve_wavelengths
from xinrefinement.core.refine.lebail import lebail_fit, lebail_weights
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.site import parse_site_model
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"


def _inputs(**over):
    pat = load_pattern(PATTERN)
    phases = [parse_cif(CIF_A), parse_cif(CIF_R)]
    kw = dict(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu",
              integrated=False)
    kw.update(over.pop("prm", {}))
    prm = ProfileParams(**kw)
    ck = dict(refine_zero=True, refine_uvw=True, n_bg=3, max_iter=60,
              tmin=5.0, tmax=90.0)
    ck.update(over.pop("cfg", {}))
    return RefineInputs(pattern=pat, phases=phases, profile=prm,
                        config=RefineConfig(**ck),
                        formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"})


# ---- P2.3 峰形全开关 -------------------------------------------------- #
def test_p23_profile_switches():
    inp = _inputs(cfg=dict(refine_eta=True, refine_asym=True,
                           refine_bfactor=True, refine_size=True,
                           refine_strain=True))
    res = solve(inp)
    assert res.success and res.rwp < 10.0
    assert res.params.X >= 0 and res.params.Y >= 0


def test_p23_asym_bfactor_bounds():
    inp = _inputs(cfg=dict(refine_asym=True, refine_bfactor=True))
    res = solve(inp)
    assert -0.05 <= res.params.asym <= 0.30
    assert 0.0 <= res.params.bfactor <= 6.0


# ---- P2.4 March-Dollase 多相 PO --------------------------------------- #
def _po_pattern(r_a, r_r):
    grid = np.arange(10.0, 90.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    y = np.zeros_like(grid)
    for path, hkl, r in ((CIF_A, (0, 0, 1), r_a), (CIF_R, (1, 1, 0), r_r)):
        st = parse_cif(path)
        this = ProfileParams(**{**prm.__dict__,
                                "po_r": {st.name: (*hkl, r)}})
        y += 1000.0 * compute_phase_profile(st, grid, this, 10.0, 90.0)
    return Pattern(two_theta=grid,
                   intensity=y + chebyshev_basis(grid, 3)
                   @ np.array([300.0, 20.0, 5.0]), meta={}), prm


@pytest.mark.parametrize("r_a,r_r", [(1.0, 1.0), (1.25, 0.8)])
def test_p24_po_multiphase(r_a, r_r):
    inp = _inputs()
    pat, prm = _po_pattern(r_a, r_r)
    from xinrefinement.core.refine.nonlinear import refine
    cfg = RefineConfig(refine_zero=False, refine_uvw=False, refine_po=True,
                       n_bg=3, tmin=10.0, tmax=90.0, max_iter=60)
    p0 = ProfileParams(**{**prm.__dict__, "po_r": {
        "anatase": (0, 0, 1, 1.0), "rutile": (1, 1, 0, 1.0)}})
    res = refine(inp.phases, pat, p0, cfg)
    # 完美拟合（Rwp≈0）时 LM 因 ftol 提前退出会把 success 标 False；
    # 判据以 Rwp 为准，success 不作硬性要求。
    assert res.rf.rwp < 5.0, res.rf.rwp
    assert res.po_r is not None
    assert abs(res.po_r["anatase"][3] - r_a) < 0.15
    assert abs(res.po_r["rutile"][3] - r_r) < 0.15


# ---- P2.5 标度 + QPA --------------------------------------------------- #
def test_p25_qpa_weight_recovery():
    inp = _inputs()
    res = solve(inp)
    wa = res.phases[0].weight_pct
    assert wa is not None and abs(wa - 50.0) < 0.5
    assert abs(sum(p.weight_pct for p in res.phases) - 100.0) < 1e-6


# ---- P2.7 波长 / 阳极 / Kα 比 ------------------------------------------ #
@pytest.mark.parametrize("anode,lam", [("Cu", 1.54056), ("Co", 1.78897),
                                       ("Mo", 0.70930)])
def test_p27_wavelength_peak_shift(anode, lam):
    """换 λ 后同一 hkl 的布拉格峰位按 arcsin(λg/2) 正确迁移。"""
    st = parse_cif(CIF_A)
    prm = ProfileParams(anode=None, wavelength=lam)
    peaks, _ = __import__(
        "xinrefinement.core.profile.struct", fromlist=["compute_peaks"]
    ).compute_peaks(st, lam, 10.0, 90.0)
    assert peaks
    # 波长越短，同一 d 的峰位越靠低角
    ref, _ = __import__(
        "xinrefinement.core.profile.struct", fromlist=["compute_peaks"]
    ).compute_peaks(st, 1.54056, 10.0, 90.0)
    if lam < 1.54056:
        assert peaks[0][0] < ref[0][0]
    elif lam > 1.54056:
        assert peaks[0][0] > ref[0][0]


def test_p27_ka_ratio_changes_intensity():
    lines_half = resolve_wavelengths(1.5406, "Cu", 0.5)
    lines_low = resolve_wavelengths(1.5406, "Cu", 0.1)
    assert lines_half[1][1] > lines_low[1][1]
    assert abs(sum(w for _, w in lines_half) - 1.0) < 1e-12


# ---- P2.8 Le Bail ------------------------------------------------------ #
def test_p28_lebail_fits_and_quantifies():
    inp = _inputs()
    res = lebail_fit(inp.phases, inp.pattern, inp.profile, inp.config,
                     max_cycles=25)
    assert res.rwp < 15.0, res.rwp
    assert len(res.intensities) == 2
    assert all(len(I) > 0 for I in res.intensities)
    assert len(res.history) == res.cycles
    assert res.ycalc.shape == inp.pattern.intensity.shape
    w = lebail_weights(inp.phases, res, inp.formulas)
    assert abs(sum(x.weight for x in w) - 1.0) < 1e-6


def test_p28_lebail_vs_rietveld_rwp():
    """Le Bail 与 Rietveld 在同一数据上都能给出合理拟合（Rwp 仅登记口径）。"""
    inp = _inputs()
    rv = solve(inp)
    lb = lebail_fit(inp.phases, inp.pattern, inp.profile, inp.config,
                    max_cycles=25)
    # Le Bail 峰形固定（不精修 U/V/W），故 Rwp 可高于 Rietveld；
    # 这里只要求达到"拟合尚可"档（plan §8.5：<20%），不做硬比较。
    assert lb.rwp < 20.0, (lb.rwp, rv.rwp)
    assert rv.rwp < 10.0


# ---- P2.9 CIF 写回 ---------------------------------------------------- #
def test_p29_write_cif_from_site_model():
    m = parse_site_model(CIF_A)
    text = write_cif(m)
    assert "_atom_site_fract_x" in text
    assert "_symmetry_equiv_pos_as_xyz" in text
    st = parse_cif_string(text, "rt")
    assert all(abs(a - b) < 1e-5 for a, b in zip(st.cell, m.cell))
    assert len(st.atoms) >= len(m.sites)
    assert roundtrip_consistent(m)


def test_p29_write_cif_from_structure():
    st = parse_cif(CIF_R)
    text = write_cif(st)
    back = parse_cif_string(text, "rt")
    assert all(abs(a - b) < 1e-5 for a, b in zip(back.cell, st.cell))
    assert len(back.atoms) == len(st.atoms)
    for a, b in zip(back.atoms, st.atoms):
        assert a[0] == b[0]
        assert np.allclose(a[1:4], b[1:4], atol=1e-5)
        assert a[4] == pytest.approx(b[4], abs=1e-4)


def test_p29_write_to_file(tmp_path):
    m = parse_site_model(CIF_A)
    out = tmp_path / "out.cif"
    write_cif(m, out)
    assert out.exists() and len(out.read_text(encoding="utf-8")) > 100
    assert parse_cif(out).name == "out"


# ---- P4.6 公开 API ---------------------------------------------------- #
def test_p46_capabilities():
    cap = api.capabilities()
    assert cap["api_version"] == api.API_VERSION
    assert "refine" in cap["entrypoints"]


def test_p46_refine_request_response():
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R),
                            formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"})
    resp = api.refine(req)
    assert resp.api_version == "1.0.0"
    assert resp.rwp < 10.0 and resp.success
    assert len(resp.phases) == 2
    # 全可 JSON 序列化（无 ndarray 泄漏）
    json.dumps(resp.as_dict())
    assert json.loads(json.dumps(req.as_dict()))["cifs"]


def test_p46_quant_and_report(tmp_path):
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R),
                            formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"})
    q = api.quant(req)
    assert len(q["phases"]) == 2
    paths = api.report(req, tmp_path)
    assert all(Path(p).exists() for p in paths.values())


def test_p46_empty_cifs_rejected():
    with pytest.raises(ValueError):
        api.refine(api.RefineRequest(pattern=PATTERN, cifs=()))
