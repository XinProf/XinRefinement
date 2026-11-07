"""v1.5 M9b：配方墙钟性能护栏验收。

覆盖：不限时零回归 / 极小预算下 xyz 步自适应跳过 / 可选步预算耗尽跳过 /
micro 步预算判断 / CLI 与 GUI 默认值接线。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import (
    DEFAULT_STEPS,
    GUI_TIME_BUDGET_S,
    RecipeRunner,
)
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"
XYZ = tuple(s for s in DEFAULT_STEPS if s.key == "xyz")[0]
MICRO = tuple(s for s in DEFAULT_STEPS if s.key == "micro")[0]


def _prm():
    return ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True)


def _cfg(**kw):
    kw.setdefault("max_iter", 25)
    return RefineConfig(n_bg=3, bg_mode="tent", tmin=5.0, tmax=90.0, **kw)


@pytest.fixture(scope="module")
def fixture_data():
    pat = load_pattern(PATTERN)
    phases = [parse_cif(CIF_A), parse_cif(CIF_R)]
    base = solve(RefineInputs(pat, phases, _prm(), _cfg()))
    return pat, phases, base


def _inputs(pat, phases, **cfg_kw):
    return RefineInputs(pat, phases, _prm(), _cfg(**cfg_kw))


def test_unlimited_budget_is_inert(fixture_data):
    """默认（预算 0）路径护栏全静默：time_report 为空、结果与显式不限时一致。"""
    pat, phases, _base = fixture_data
    inp = _inputs(pat, phases, refine_xyz=True)
    runner1 = RecipeRunner()
    r1, rec1 = runner1.run_all(inp)
    runner2 = RecipeRunner(time_budget_s=0.0)
    r2, rec2 = runner2.run_all(inp)
    assert r1.rwp == pytest.approx(r2.rwp, abs=0.0)
    assert runner1.time_report == [] and runner2.time_report == []
    assert [x.status for x in rec1] == [x.status for x in rec2]


def test_tiny_budget_skips_xyz_and_optional_steps(fixture_data):
    """极小预算：xyz 步被护栏跳过（不足 1 次迭代），micro/B 被连跑护栏跳过，
    最终 Rwp 与「没有 xyz/micro/B」一致（护栏只省时、不破坏结果）。"""
    pat, phases, _base = fixture_data
    inp = _inputs(pat, phases, refine_xyz=True)
    runner = RecipeRunner(time_budget_s=0.05)
    res, recs = runner.run_all(inp)
    by_key = {r.key: r for r in recs}
    assert by_key["xyz"].status == "skipped"
    assert "时间护栏" in by_key["xyz"].message
    assert by_key["micro"].status == "skipped"
    assert by_key["B"].status == "skipped"
    assert runner.time_report, "护栏动作必须留痕"
    # 结果 = profile 步的产物：护栏不改变已完成的精修成果
    r_ref, _ = RecipeRunner().run_all(
        _inputs(pat, phases, refine_xyz=False),
        steps=tuple(s for s in DEFAULT_STEPS if s.key in
                    ("zero", "bg", "scale", "cell", "profile")))
    assert res.rwp == pytest.approx(r_ref.rwp, abs=1e-9)


def test_micro_guard_skips_probe_and_step_when_exhausted(fixture_data):
    """micro 步在预算耗尽时：跳过 PO 试探且不足 1 次迭代时整步 skipped。"""
    pat, phases, base = fixture_data
    runner = RecipeRunner(time_budget_s=0.0)
    runner.time_budget_s = 1.0          # 只为启动时钟；剩余瞬间耗尽
    runner._start_clock()
    res, rec = runner.run_step(MICRO, _inputs(
        pat, phases, po_probe=True, max_iter=25), base)
    assert rec.status == "skipped"
    assert "时间护栏" in rec.message
    assert res is base                  # 原样返回，不破坏链


def test_cli_flag_parses():
    """CLI --time-budget-min 接线（默认 0 = 不限）。"""
    from xinrefinement.cli.refine import build_parser

    args = build_parser().parse_args(
        ["refine", "x.xy", "a.cif", "--time-budget-min", "30"])
    assert args.time_budget_min == pytest.approx(30.0)
    args0 = build_parser().parse_args(["refine", "x.xy", "a.cif"])
    assert args0.time_budget_min == 0.0


def test_gui_default_budget_wiring():
    """GUI 出厂默认 45 min；worker 把分钟数换算成秒传给 runner。"""
    assert GUI_TIME_BUDGET_S == 2700.0
    from xinrefinement.gui.workers import RefineWorker
    from xinrefinement.core.refine.recipe import RecipeRunner as R

    # 不实例化 QThread（无需 Qt 事件循环），只验证默认值常量与换算口径
    assert int(GUI_TIME_BUDGET_S // 60) == 45
    runner = R(time_budget_s=45 * 60.0)
    assert runner.time_budget_s == pytest.approx(2700.0)
    assert RefineWorker is not None
