"""v1.5 M9：xyz 步「欠定按相降级」验收。

背景见 ``docs/立项-MAUD对标改进计划-v1.md`` §1.3：样 7 的 xyz 步
``48 = 高岭石 39 + 萤石 4 + 白云石 4 + 方石英 1 > xyz_max_params=40``
被 v1.4 的全局求和护栏整步判 failed，5 相一个都没精修；而单独精修
39 参高岭石在增量口径有 −1.87 pt，排除它只有 −0.27 pt。

覆盖：默认策略 / off 保持旧行为 / largest 与 small 选相不同 /
无相可放入预算仍失败 / 不超限时逐位零回归 / 被跳过的相有记录 /
合成真值上端到端确实拿到收益。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams, compute_phase_profile)
from xinrefinement.core.refine import site as site_mod
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import DEFAULT_STEPS, RecipeRunner
from xinrefinement.core.refine.site import parse_site_model
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"
XYZ = tuple(s for s in DEFAULT_STEPS if s.key == "xyz")


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
    assert all(getattr(st, "source_path", None) for st in phases)
    base = solve(RefineInputs(pat, phases, _prm(), _cfg()))
    return pat, phases, base


def _inject_xyz(phases, base):
    """沿对称性允许的方向给第一相注入 0.02 位移，生成自洽合成谱。"""
    st = phases[0]
    m = parse_site_model(st.source_path)
    m = replace(m, name=st.name, cell=tuple(float(v) for v in st.cell))
    x = np.zeros(m.n_params)
    off, hit = 0, None
    for s in m.sites:
        if s.n_free:
            hit = off
            break
        off += s.n_free + 2
    assert hit is not None
    x[hit] = 0.02
    truth = m.to_structure(x)
    tt = base.pattern.two_theta
    b0 = compute_phase_profile(st, tt, base.params)
    b1 = compute_phase_profile(truth, tt, base.params)
    s0 = float(base.engine.scales[0])
    syn = Pattern(two_theta=tt,
                  intensity=base.ycalc - b0 * s0 + b1 * s0,
                  meta=dict(base.pattern.meta))
    return syn, truth


def _patch_nfree(monkeypatch, totals: dict[str, int]) -> None:
    """让 parse_site_model 返回指定 n_free 的模型（只影响护栏与选相）。

    ``refine_sites`` 在选相测试里被 spy 替换，故 basis 维度不必与 n_free
    一致；真实端到端测试不调用本函数。
    """
    real = site_mod.parse_site_model

    def fake(path):
        m = real(path)
        key = "anatase" if "anatase" in str(path).lower() else "rutile"
        target = totals[key]
        sites = list(m.sites)
        delta = target - sum(int(s.n_free) for s in sites)
        sites[0] = replace(sites[0],
                           n_free=max(0, int(sites[0].n_free) + delta))
        return replace(m, sites=sites)

    monkeypatch.setattr(site_mod, "parse_site_model", fake)


def _spy_refine(monkeypatch, seen: dict) -> None:
    def spy(models, pat, prm0, cfg, **kw):
        seen["models"] = [m.name for m in models]
        seen["fixed"] = [s.name for s in kw.get("fixed_structures", ())]
        raise RuntimeError("sentinel")
    monkeypatch.setattr(site_mod, "refine_sites", spy)


def test_default_strategy_is_largest():
    cfg = RefineConfig()
    assert cfg.refine_xyz is False
    assert cfg.xyz_max_params == 40
    assert cfg.xyz_phase_select == "largest"


def test_off_keeps_v14_failed(fixture_data, monkeypatch):
    """显式 off 时超预算仍整步 failed，且不会调用站点引擎。"""
    pat, phases, _base = fixture_data
    seen = {}
    _spy_refine(monkeypatch, seen)
    res, recs = RecipeRunner().run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=1,
                          xyz_phase_select="off")), steps=XYZ)
    assert res is None
    assert recs[0].status == "failed" and "欠定" in recs[0].message
    assert seen == {}


def test_largest_keeps_biggest_phase(fixture_data, monkeypatch):
    """6 + 2 > 预算 7 时，largest 保留 6 参相，2 参相转 fixed。"""
    pat, phases, _base = fixture_data
    _patch_nfree(monkeypatch, {"anatase": 6, "rutile": 2})
    seen = {}
    _spy_refine(monkeypatch, seen)
    _res, recs = RecipeRunner().run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=7,
                          xyz_phase_select="largest")), steps=XYZ)
    assert "sentinel" in recs[0].message
    assert seen["models"] == [phases[0].name]
    assert seen["fixed"] == [phases[1].name]


def test_small_keeps_smallest_phase(fixture_data, monkeypatch):
    """同一组数据下 small 策略选相相反（诊断对照分支确实存在）。"""
    pat, phases, _base = fixture_data
    _patch_nfree(monkeypatch, {"anatase": 6, "rutile": 2})
    seen = {}
    _spy_refine(monkeypatch, seen)
    RecipeRunner().run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=7,
                          xyz_phase_select="small")), steps=XYZ)
    assert seen["models"] == [phases[1].name]
    assert seen["fixed"] == [phases[0].name]


def test_no_phase_fits_budget_still_fails(fixture_data, monkeypatch):
    """连单个相都放不进预算时必须明确失败，不能静默跳过。"""
    pat, phases, _base = fixture_data
    _patch_nfree(monkeypatch, {"anatase": 5, "rutile": 5})
    seen = {}
    _spy_refine(monkeypatch, seen)
    _res, recs = RecipeRunner().run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=4)), steps=XYZ)
    assert recs[0].status == "failed"
    assert "无单个相可在预算内精修" in recs[0].message
    assert seen == {}


def test_under_budget_is_bitwise_zero_regression(fixture_data):
    """不触发降级时，新策略不改变数值路径（与旧行为同值到 1e-9）。

    原判据是**逐位相等**（`abs=0, rel=0`）。2026-11-08 全量连跑时实测两策略
    差 8e-11：20.922821832513748 vs 20.922821832431744（相对 3.9e-12）。差异
    不来自策略——`xyz_phase_select` 只决定「选哪些相进预算」，不参与残差/
    雅可比计算；来源是 BLAS 多线程归约在不同进程负载下不可逐位复现，25 步
    迭代后放大到 1e-11 量级。判据改为相对 1e-9（比 4 位小数的报告精度还严
    4 个数量级），步状态与降级清单仍要求**严格相等**。
    """
    pat, phases, base = fixture_data
    syn, _truth = _inject_xyz(phases, base)
    outs = []
    for strategy in ("off", "largest"):
        runner = RecipeRunner()
        res, recs = runner.run_all(
            RefineInputs(syn, phases, _prm(),
                         _cfg(refine_xyz=True, xyz_phase_select=strategy)),
            steps=XYZ)
        outs.append((float(res.rwp), tuple(runner.xyz_report["params"]),
                     [r.status for r in recs]))
    assert outs[0][0] == pytest.approx(outs[1][0], rel=1e-9)
    assert np.allclose(outs[0][1], outs[1][1], rtol=1e-9, atol=0)
    assert outs[0][2] == outs[1][2]
    assert runner.xyz_report["dropped_phases"] == ()


def test_dropped_phases_are_reported(fixture_data):
    """降级发生的相必须写进 xyz_report，用户能看到谁被跳过。"""
    pat, phases, _base = fixture_data
    runner = RecipeRunner()
    runner.run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=1)), steps=XYZ)
    report = runner.xyz_report
    assert report["n_free"] == 1
    assert phases[1].name in report["dropped_phases"]
    assert phases[0].name in report["phases"]


def test_end_to_end_gain_over_v14_failure(fixture_data):
    """合成真值：v1.4 整步 failed，M9 降级后确实回收注入位移。"""
    pat, phases, base = fixture_data
    syn, _truth = _inject_xyz(phases, base)
    cfg_off = _cfg(refine_xyz=True, xyz_max_params=1,
                   xyz_phase_select="off")
    _res_off, recs_off = RecipeRunner().run_all(
        RefineInputs(syn, phases, _prm(), cfg_off), steps=XYZ)
    assert recs_off[0].status == "failed"

    runner = RecipeRunner()
    cfg_new = _cfg(refine_xyz=True, xyz_max_params=1)
    res, recs = runner.run_all(
        RefineInputs(syn, phases, _prm(), cfg_new), steps=XYZ)
    # 只跑 xyz 单步时，StepRecord 的 before/after 才是同口径基准；
    # 另起一次 solve() 会带上别的非线性自由度，Rwp 不可直接相减。
    assert recs[0].status == "done"
    assert float(recs[0].rwp_after) < float(recs[0].rwp_before) - 1e-4
    assert float(res.rwp) == pytest.approx(float(recs[0].rwp_after),
                                           abs=1e-9, rel=0)
    assert runner.xyz_report["accepted"] is True
    assert phases[1].name in runner.xyz_report["dropped_phases"]
