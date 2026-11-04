"""P1-PRE · 虚拟样合成器验收（P1/P2 验收地基）。

覆盖：
1. seed 可复现（同 spec 两次逐位一致，不同 seed 不同）；
2. QPA 质量分数自洽：合成 → solve → 回收真值 < 0.5pp；
3. 噪声理论 Rwp 有定义且量级合理（P2.2 / §8.5 判据依据）；
4. 参数化能力：零点 / 样品位移 / 弯背景 / 尺寸应变 / 波长可注入；
5. 批量写数据集 + manifest。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import gen_virtual as gv  # noqa: E402

from xinrefinement.core.patterns import load_pattern  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams  # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig  # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve  # noqa: E402

A = "xinrefinement/data/anatase.cif"
R = "xinrefinement/data/rutile.cif"


def _two_phase(wa: float = 50.0, **kw) -> gv.VirtualSpec:
    return gv.VirtualSpec(
        phases=(gv.PhaseSpec(cif=A, weight_pct=wa, formula="O2 Ti"),
                gv.PhaseSpec(cif=R, weight_pct=100.0 - wa, formula="O2 Ti")),
        **kw)


def test_seed_reproducible():
    spec = _two_phase()
    p1, t1 = gv.synthesize(spec)
    p2, t2 = gv.synthesize(spec)
    assert np.array_equal(p1.intensity, p2.intensity)
    assert np.array_equal(p1.two_theta, p2.two_theta)
    assert t1["phases_detail"] == t2["phases_detail"]

    other = gv.VirtualSpec(**{**spec.__dict__, "seed": spec.seed + 1})
    p3, _ = gv.synthesize(other)
    assert not np.array_equal(p1.intensity, p3.intensity)


@pytest.mark.parametrize("wa", (5.0, 50.0, 95.0))
def test_qpa_weight_recovery(wa):
    """合成谱经 solve 精修，质量分数回收误差 < 0.5pp。"""
    spec = _two_phase(wa)
    pat, truth = gv.synthesize(spec)
    phases = [parse_cif(ROOT / A), parse_cif(ROOT / R)]
    for i, st in enumerate(phases):
        st.name = f"phase{i}"
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3,
                       max_iter=40, tmin=spec.tmin, tmax=spec.tmax)
    res = solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                             config=cfg,
                             formulas={"phase0": "O2 Ti", "phase1": "O2 Ti"}))
    assert res.success, res.warnings
    got = res.phases[0].weight_pct
    assert got is not None
    assert abs(got - wa) < 0.5, f"wa_true={wa} got={got}"
    assert res.rwp < 10.0


def test_noise_theory_rwp_defined():
    """噪声理论 Rwp 有明确定义且量级合理（≈3%，与泊松计数自洽）。"""
    pat, truth = gv.synthesize(_two_phase())
    assert "rwp_noise_definition" in truth
    assert 1.0 < truth["rwp_noise_theory"] < 10.0
    assert truth["n_points"] == pat.two_theta.size


def test_parameterized_knobs_change_spectrum():
    """零点 / 位移 / 弯背景 / 尺寸应变 / 波长各自能改变谱形。"""
    base_p, _ = gv.synthesize(_two_phase(noise="none"))
    variants = {
        "zero": _two_phase(noise="none", zero=0.25),
        "disp": _two_phase(noise="none", disp=0.20),
        "bent_bg": _two_phase(noise="none", bg_mode="tent",
                              bg_coeffs=(300.0, 120.0, 80.0, 200.0)),
        "size": _two_phase(noise="none", Y=0.15),
        "wavelength": _two_phase(noise="none", anode=None, wavelength=1.78897),
    }
    for name, spec in variants.items():
        p, _ = gv.synthesize(spec)
        assert p.two_theta.size == base_p.two_theta.size
        assert not np.array_equal(p.intensity, base_p.intensity), name


def test_write_dataset(tmp_path):
    """批量写 .xy + *_truth.json + manifest.json，且 .xy 可被读入。"""
    specs = [_two_phase(wa, name="v") for wa in (25.0, 50.0)]
    m = gv.write_dataset(specs, tmp_path)
    assert m["n"] == 2
    for e in m["samples"]:
        xy = tmp_path / e["file"]
        assert xy.exists()
        pat = load_pattern(xy)
        assert pat.two_theta.size > 100
        assert (tmp_path / e["truth"]).exists()
    assert (tmp_path / "manifest.json").exists()
