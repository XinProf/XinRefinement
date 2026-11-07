"""v1.5 M8：PO 试探命中相改用球谐织构播种（MAUD Harmonic 口径）的护栏。

背景：MAUD 对样 7 的高岭石/萤石/白云石统一用 Harmonic 8 阶逐相织构，
而 March–Dollase 单轴 r 只能表达一维纤维分布，且 r 与标度强相关
（实测样 7 萤石 r 撞上界 5.0，几乎只换了标度）。本测试保证新分支
只在显式开启时生效，并把轴正确地写进 ``prm.texture``。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import DEFAULT_STEPS, RecipeRunner
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"
MICRO = tuple(s for s in DEFAULT_STEPS if s.key == "micro")[0]


def _prm():
    return ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True)


def _cfg(**kw):
    kw.setdefault("max_iter", 5)
    return RefineConfig(n_bg=3, bg_mode="tent", tmin=5.0, tmax=90.0, **kw)


@pytest.fixture(scope="module")
def fixture_data():
    pat = load_pattern(PATTERN)
    phases = [parse_cif(CIF_A), parse_cif(CIF_R)]
    base = solve(RefineInputs(pat, phases, _prm(), _cfg(max_iter=25)))
    return pat, phases, base


def test_probe_to_texture_seeds_harmonic(fixture_data, monkeypatch):
    """显式开 po_probe_to_texture：命中相写进 prm.texture（harmonic），不留 po_r。"""
    import xinrefinement.core.refine.recipe as R

    # anatase/rutile 默认在 DEFAULT_PO_HKL 里不参与试探，这里清空以走到播种分支
    monkeypatch.setattr(R, "DEFAULT_PO_HKL", {})
    pat, phases, base = fixture_data
    cfg = _cfg(po_probe=True, po_probe_min_gain=-1.0, po_probe_max_phases=1,
               po_probe_axes=((1, 0, 0),), po_probe_max_iter=2,
               po_probe_to_texture=True, po_probe_texture_degree=4,
               refine_texture=True)
    res, rec = RecipeRunner().run_step(
        MICRO, RefineInputs(pat, phases, _prm(), cfg), base)
    assert rec.status == "done"
    tex = res.params.texture or {}
    assert tex, "命中相必须写进 prm.texture"
    seeds = [e for e in tex.values()
             if isinstance(e, dict) and e.get("model") == "harmonic"]
    assert seeds and all(e.get("degree") == 4 for e in seeds)
    assert all(len(e.get("coeffs") or []) == 2 for e in seeds)  # 阶 4 -> P2/P4
    # 试探轴必须写进织构条目（这里只放了 (1,0,0) 一个候选）
    assert all(tuple(e.get("axis")) == (1, 0, 0) for e in seeds)
    # 注意：po_r 里仍会有 DEFAULT_PO_HKL 的引擎自动补位（anatase (001)/
    # rutile (110)），那不是试探产物；forward 层对已开织构的相忽略 po_r。


def test_probe_default_keeps_md(fixture_data, monkeypatch):
    """默认（po_probe_to_texture=False）：仍是 March–Dollase 路径，逐位不变。"""
    import xinrefinement.core.refine.recipe as R

    monkeypatch.setattr(R, "DEFAULT_PO_HKL", {})
    pat, phases, base = fixture_data
    cfg = _cfg(po_probe=True, po_probe_min_gain=-1.0, po_probe_max_phases=1,
               po_probe_axes=((1, 0, 0),), po_probe_max_iter=2)
    res, rec = RecipeRunner().run_step(
        MICRO, RefineInputs(pat, phases, _prm(), cfg), base)
    assert rec.status == "done"
    assert res.params.po_r, "MD 路径必须写 po_r"
    assert not (res.params.texture or {}), "默认路径不应播种织构"
