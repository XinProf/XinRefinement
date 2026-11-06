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
    """8 步覆盖草图自上而下顺序；v1.4 起 xyz/B 均已落地（opt-in 开启）。"""
    assert len(DEFAULT_STEPS) == 8
    keys = [s.key for s in DEFAULT_STEPS]
    assert keys[:4] == ["zero", "bg", "scale", "cell"]
    unavailable = [s.key for s in DEFAULT_STEPS if not s.available]
    assert unavailable == []


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
    assert sum(r.status == "skipped" for r in records) == 1
    assert runner.state.current == len(DEFAULT_STEPS)
    assert len(runner.state.snapshots) == len(DEFAULT_STEPS) - 1  # xyz 默认跳过

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


def test_cell_step_really_refines_cell():
    """cell 步必须**真的**改晶胞，且精修结果要留给后续步骤。

    历史缺陷（v1.1.0 及以前）：``config_for`` 从不设 ``refine_cell``，
    注释里引用的 ``run_cell_step`` 根本不存在 —— 这一步 status=done，
    但 Rwp 前后逐位相同（实样实测 35.4108% → 35.4108%），属于假装执行。
    本测试锁两件事：① 晶胞数值变了；② 新晶胞进了后续步骤共用的相列表。
    """
    inp = _inputs()
    runner = RecipeRunner()
    by_key = {s.key: s for s in DEFAULT_STEPS}
    res = None
    for key in ("zero", "bg", "scale"):
        res, _ = runner.run_step(by_key[key], inp, res)

    before = [tuple(round(v, 9) for v in s.cell) for s in runner.phases]
    res, rec = runner.run_step(by_key["cell"], inp, res)

    assert rec.status == "done"
    after = [tuple(round(v, 9) for v in s.cell) for s in runner.phases]
    assert after != before, "cell 步没有改动晶胞 —— 又退回假执行了"
    # 后续步骤（profile/micro）拿到的相列表必须是精修后的
    assert [tuple(s.cell) for s in runner.phases] == [
        tuple(s.cell) for s in runner._phases_for(inp)]
    # 记录里要能看出改了哪个相（结果区可读性）
    assert "晶胞已精修" in rec.message

    res2, _ = runner.run_step(by_key["profile"], inp, res)
    assert res2.rwp <= res.rwp + 1e-9


def test_cell_step_keeps_phase_metadata():
    """晶胞回写不能丢元数据 —— 丢了 QPA 会静默退化成 weight_pct=None。"""
    inp = _inputs()
    runner = RecipeRunner()
    by_key = {s.key: s for s in DEFAULT_STEPS}
    res = None
    for key in ("zero", "bg", "scale", "cell"):
        res, _ = runner.run_step(by_key[key], inp, res)
    for st in runner.phases:
        assert st.formula, f"{st.name} 丢失化学式"
        assert getattr(st, "z_declared", None), f"{st.name} 丢失 Z"
    assert any(p.weight_pct is not None for p in res.phases), \
        "走完晶胞精修后 QPA 整表变 None（元数据在回写时丢了）"

