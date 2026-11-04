"""P3.3 · 导航式精修配方验收（core 层，无 GUI）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import (
    DEFAULT_STEPS,
    RecipeRunner,
    RecipeState,
    RefineStep,
)
from xinrefinement.core.refine.solve import RefineInputs

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


def test_default_steps_cover_sketch():
    """8 步覆盖草图自上而下顺序；xyz/B 标记不可用（不做假执行）。"""
    assert len(DEFAULT_STEPS) == 8
    keys = [s.key for s in DEFAULT_STEPS]
    assert keys[:4] == ["zero", "bg", "scale", "cell"]
    unavailable = [s.key for s in DEFAULT_STEPS if not s.available]
    assert unavailable == ["xyz", "B"]


def test_step_config_translation():
    """每步只放开对应参数组（zero 步不精修 uvw，profile 步放开）。"""
    inp = _inputs()
    by_key = {s.key: s for s in DEFAULT_STEPS}
    zero_cfg = by_key["zero"].config_for(inp.config)
    assert zero_cfg.refine_zero is True and zero_cfg.refine_uvw is False
    prof_cfg = by_key["profile"].config_for(inp.config)
    assert prof_cfg.refine_uvw is True and prof_cfg.refine_eta is True
    micro_cfg = by_key["micro"].config_for(inp.config)
    assert micro_cfg.refine_po is True and micro_cfg.refine_size is True


def test_run_single_step():
    res, rec = RecipeRunner().run_step(DEFAULT_STEPS[0], _inputs())
    assert rec.status == "done"
    assert rec.rwp_after is not None and rec.rwp_after < 10.0
    assert res is not None and res.rwp == rec.rwp_after


def test_unavailable_step_is_skipped():
    runner = RecipeRunner()
    xyz = next(s for s in DEFAULT_STEPS if s.key == "xyz")
    res, rec = runner.run_step(xyz, _inputs())
    assert rec.status == "skipped" and res is None
    assert "P1.3" in rec.message


def test_run_all_and_rollback():
    """连跑全配方 → 记录数=步骤数 → 可回退到任意快照。"""
    runner = RecipeRunner()
    result, records = runner.run_all(_inputs())
    assert result is not None and result.rwp < 10.0
    assert len(records) == len(DEFAULT_STEPS)
    assert sum(r.status == "skipped" for r in records) == 2
    assert runner.state.current == len(DEFAULT_STEPS)
    assert len(runner.state.snapshots) == len(DEFAULT_STEPS) - 2  # 跳过步不快照

    snap = runner.state.rollback(1)
    assert snap is not None and len(snap) == 9
    assert runner.state.current == 2
    assert len(runner.state.records) == 2
    assert runner.state.rollback(999) is None


def test_cancel_stops_early():
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= 3

    runner = RecipeRunner()
    _res, records = runner.run_all(_inputs(), cancel_cb=cancel)
    assert len(records) < len(DEFAULT_STEPS)


def test_state_default_is_independent():
    """dataclass 默认 list 不共享（避免跨实例污染）。"""
    a, b = RecipeState(), RecipeState()
    a.records.append(object())
    assert b.records == []
