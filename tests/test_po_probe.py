"""v1.4 任务 #19：micro 步 March–Dollase 惯习面自动试探。"""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams, compute_phase_profile)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import (
    DEFAULT_STEPS, RecipeRunner, RefineStep)
from xinrefinement.core.refine.solve import RefineInputs, solve

VB = Path("tests/data/virtual_b")
DATA = Path("xinrefinement/data")
MICRO = tuple(s for s in DEFAULT_STEPS if s.key == "micro")


@pytest.fixture(scope="module")
def fixture_data():
    pat = load_pattern(VB / "v50_wide.xy")
    # 改名躲开 DEFAULT_PO_HKL 的自动惯习面注入，只测「未知相」的试探路径
    phases = []
    for new_name, f in (("phaseA", "anatase.cif"), ("phaseB", "rutile.cif")):
        st = copy.copy(parse_cif(DATA / f))
        st.name = new_name
        phases.append(st)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3,
                       bg_mode="tent", tmin=5.0, tmax=90.0, max_iter=25)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    base = solve(RefineInputs(pat, phases, prm, cfg))
    name = phases[0].name
    # 注入真值 PO：锐钛矿 (001) r=0.6（强 c 轴织构）
    truth = replace(base.params, po_r={name: (0, 0, 1, 0.6)})
    b0 = compute_phase_profile(phases[0], base.pattern.two_theta, base.params)
    b1 = compute_phase_profile(phases[0], base.pattern.two_theta, truth)
    s0 = float(base.engine.scales[0])
    y = base.ycalc - b0 * s0 + b1 * s0
    syn = Pattern(two_theta=base.pattern.two_theta, intensity=y,
                  meta=dict(pat.meta))
    return syn, phases, base.params, name


def _micro(cfg_extra: dict, data, po_r=None):
    syn, phases, base_params, name = data
    cfg = RefineConfig(n_bg=3, bg_mode="tent", tmin=5.0, tmax=90.0,
                       max_iter=25, **cfg_extra)
    prm = replace(base_params, po_r=po_r)
    runner = RecipeRunner()
    res, recs = runner.run_all(RefineInputs(syn, phases, prm, cfg),
                               steps=MICRO)
    return res, recs, runner


def test_config_defaults_off():
    """默认关：与 v1.3 契约一致，避免悄悄增加精修耗时。"""
    cfg = RefineConfig()
    assert cfg.po_probe is False
    assert cfg.po_probe_min_gain == 0.3
    assert cfg.po_probe_max_phases == 2
    assert len(cfg.po_probe_axes) >= 3


def test_probe_finds_injected_axis(fixture_data):
    syn, phases, base_params, name = fixture_data
    off, _, r_off = _micro({"po_probe": False}, fixture_data)
    on, recs, r_on = _micro({"po_probe": True, "po_probe_min_gain": 0.3},
                            fixture_data)
    # 未开试探时 PO 失配无法收敛（success=False 属正常）；只比 Rwp
    assert np.isfinite(off.rwp) and np.isfinite(on.rwp)
    # 真值 (001) 应被试探选中且显著优于不开试探
    assert on.rwp < off.rwp - 10.0
    chosen = [row["phase"] for row in r_on.po_probe_report
             if row.get("gain") is not None]
    assert set(chosen) <= set(st.name for st in phases)
    assert name in chosen
    best = max(r_on.po_probe_report, key=lambda r: r["gain"] or -1e9)
    assert best["phase"] == name
    assert best["axis"] == [0, 0, 1]
    assert on.params.po_r and name in on.params.po_r
    assert "PO 试探" in recs[-1].message
    assert r_off.po_probe_report == []


def test_probe_respects_user_po_and_texture(fixture_data):
    """用户已配置的相不试探；开 EWIMV 织构的相互斥跳过。"""
    syn, phases, base_params, name = fixture_data
    from xinrefinement.core.profile.forward import default_texture_grid

    po_r = {name: (0, 0, 1, 0.9)}
    prm = replace(base_params, po_r=po_r)
    _res, _recs, runner = _micro({"po_probe": True}, fixture_data, po_r=po_r)
    assert all(row["phase"] != name for row in runner.po_probe_report)

    tex = {name: {"axis": (0, 0, 1), "grid": default_texture_grid()}}
    cfg = RefineConfig(n_bg=3, bg_mode="tent", tmin=5.0, tmax=90.0,
                       max_iter=8, po_probe=True, refine_texture=True)
    runner2 = RecipeRunner()
    runner2.run_all(RefineInputs(syn, phases,
                                 replace(prm, po_r=None, texture=tex), cfg),
                    steps=MICRO)
    assert all(row["phase"] != name for row in runner2.po_probe_report)


def test_probe_threshold_rejects_all(fixture_data):
    """阈值拉到不可能的高值 → 不启用 PO，结果与不开试探一致。"""
    off, _, _ = _micro({"po_probe": False}, fixture_data)
    hi, recs, runner = _micro({"po_probe": True,
                               "po_probe_min_gain": 999.0}, fixture_data)
    assert "无相达到增益阈值" in recs[-1].message
    assert hi.rwp == pytest.approx(off.rwp, rel=1e-9)
    assert runner.po_probe_report  # 试探仍然执行并留痕
