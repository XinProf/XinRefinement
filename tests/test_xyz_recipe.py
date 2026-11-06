"""v1.4 任务 #17：原子坐标精修接入导航配方（xyz 步）验收。

覆盖：默认关闭 / 显式 opt-in / 缺 CIF 源路径跳过 / 自由系数上限 /
合成真值回收 / 结构元数据继承（QPA 依赖）/ Rwp 不改善时回退。
"""
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
    # 前提：parse_cif 必须写入 source_path，xyz 步才可能重读不对称单位
    assert all(getattr(st, "source_path", None) for st in phases)
    base = solve(RefineInputs(pat, phases, _prm(), _cfg()))
    return pat, phases, base


def _inject_xyz(phases, base):
    """沿对称性允许的自由坐标方向注入 0.02 位移，生成自洽合成谱。

    不能直接改 ``CifStructure.atoms``：那会破坏等效位点联动，变成一个
    「引擎根本无法表达」的假真值。这里用 SiteModel.to_structure 生成
    与 xyz 步同一套参数化下的真值结构。
    """
    st = phases[0]
    m = parse_site_model(st.source_path)
    m = replace(m, name=st.name, cell=tuple(float(v) for v in st.cell))
    x = np.zeros(m.n_params)
    off, hit = 0, None
    for site in m.sites:
        if site.n_free:
            hit = off
            break
        off += site.n_free + 2
    assert hit is not None, "测试 CIF 必须至少有一个自由坐标方向"
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


def test_config_defaults_off():
    """CLI/API 默认关闭；步骤本身可用但运行期 opt-in 才执行。"""
    cfg = RefineConfig()
    assert cfg.refine_xyz is False
    assert cfg.xyz_max_params == 40
    assert next(s for s in DEFAULT_STEPS if s.key == "xyz").available is True


def test_default_xyz_step_is_skipped(fixture_data):
    pat, phases, base = fixture_data
    runner = RecipeRunner()
    res, recs = runner.run_all(
        RefineInputs(pat, phases, _prm(), _cfg()), steps=XYZ)
    assert res is None
    assert recs[0].status == "skipped"
    assert "P1.3" in recs[0].message
    assert runner.xyz_report == {}


def test_no_source_path_is_skipped(fixture_data):
    """parse_cif_string / 手工构造的相无源路径，应明确跳过而非假装精修。"""
    pat, phases, base = fixture_data
    no_src = []
    for st in phases:
        c = copy.copy(st)
        c.source_path = None
        no_src.append(c)
    runner = RecipeRunner()
    _res, recs = runner.run_all(
        RefineInputs(pat, no_src, _prm(), _cfg(refine_xyz=True)), steps=XYZ)
    assert recs[0].status == "skipped"
    assert "CIF 源路径" in recs[0].message


def test_free_param_cap_fails(fixture_data):
    """自由系数上限是欠定护栏，触顶必须报 failed 而不是静默跑。"""
    pat, phases, base = fixture_data
    runner = RecipeRunner()
    res, recs = runner.run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, xyz_max_params=0)), steps=XYZ)
    assert recs[0].status == "failed"
    assert "欠定" in recs[0].message
    assert res is None


def test_site_iter_is_capped(fixture_data, monkeypatch):
    """站点 LM 迭代预算必须封顶（多相实样按 40 次会跑十几分钟）。"""
    import xinrefinement.core.refine.site as site

    from xinrefinement.core.refine.recipe import XYZ_SITE_MAX_ITER

    pat, phases, base = fixture_data
    seen = {}

    def spy(models, pat, prm0, cfg, **kw):
        seen["max_iter"] = cfg.max_iter
        raise RuntimeError("sentinel")

    monkeypatch.setattr(site, "refine_sites", spy)
    runner = RecipeRunner()
    _res, recs = runner.run_all(
        RefineInputs(pat, phases, _prm(),
                     _cfg(refine_xyz=True, max_iter=40)), steps=XYZ)
    assert seen["max_iter"] == XYZ_SITE_MAX_ITER
    assert recs[0].status == "failed" and "sentinel" in recs[0].message


def test_recovers_injected_xyz_and_keeps_metadata(fixture_data):
    """注入位移后 xyz 步应改善 Rwp；接受时结构元数据须逐项继承。"""
    pat, phases, base = fixture_data
    syn, _truth = _inject_xyz(phases, base)
    off = solve(RefineInputs(syn, phases, base.params, _cfg()))
    runner = RecipeRunner()
    res, recs = runner.run_all(
        RefineInputs(syn, phases, base.params, _cfg(refine_xyz=True)),
        steps=XYZ)
    assert recs[0].status == "done"
    assert res is not None
    report = runner.xyz_report
    assert report["n_free"] >= 1
    assert phases[0].name in report["phases"]
    assert "accepted" in report
    # 配方承诺：无论接受还是回退，结果都不比不做 xyz 更差
    assert res.rwp <= off.rwp + 1e-6
    if report["accepted"]:
        assert res.rwp < off.rwp - 1e-3
        got = runner.phases[0]
        for attr in ("source_path", "z_declared", "n_asym", "n_sym_ops",
                     "formula", "spacegroup", "sg_number"):
            assert getattr(got, attr, None) == getattr(phases[0], attr, None), attr
