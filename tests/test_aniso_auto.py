"""v1.5 M4：Popa LB 各向异性**自动启用**（``RefineConfig.aniso_auto``）。

背景：v1.3 落地了逐相各向异性，但必须由调用方在 ``prm.aniso`` 里逐相写好
系数，否则 ``refine_aniso=True`` 只会打一条「没有相配置系数」的告警——
**开关打开等于没开**（与 K17 的 EWIMV 织构同族缺陷）。实样对拍里
``combo_tex_aniso`` 阶段是在基准脚本里手工 ``aniso_default()`` 补齐才有效的。

M4 把「补起点」下沉到 ``solve()``：``aniso_auto=True`` 时逐相补各向同性
起点（size 6 参），方向数不足的相自动跳过（不整体报错），显式配置的相
仍走硬护栏。默认关 → 既有 golden 逐位零回归。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.params.registry import build_registry_from_config
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, aniso_default
from xinrefinement.core.refine.recipe import DEFAULT_STEPS, RecipeRunner
from xinrefinement.core.refine.solve import RefineInputs, solve

DATA = Path(__file__).parent.parent / "xinrefinement" / "data"
VIRTUAL_B = Path(__file__).parent / "data" / "virtual_b"


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]


@pytest.fixture(scope="module")
def pat():
    return load_pattern(VIRTUAL_B / "v50_wide.xy")


def _cfg(**kw):
    from xinrefinement.core.refine.nonlinear import RefineConfig

    base = dict(refine_zero=True, refine_uvw=True, n_bg=3,
                max_iter=8, tmin=5.0, tmax=90.0)
    base.update(kw)
    return RefineConfig(**base)


def test_default_off_keeps_no_aniso(structs, pat):
    """默认 aniso_auto=False：不配置各向异性时行为与 v1.4 完全一致。"""
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    res = solve(RefineInputs(pattern=pat, phases=structs, profile=prm,
                             config=_cfg()))
    assert res.params.aniso is None
    assert not any("自动启用" in w for w in res.warnings)
    # 未配系数时也不能凭空生成槽位
    reg = build_registry_from_config(res.config, res.params, len(structs))
    assert not any(".aniso." in key for key in reg.labels())


def test_auto_seeds_every_phase_and_takes_effect(structs, pat):
    """K17 型验收：auto 打开后**真的**产生了各向异性自由度并改变结果。"""
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    off = solve(RefineInputs(pattern=pat, phases=structs, profile=prm,
                             config=_cfg()))
    on = solve(RefineInputs(pattern=pat, phases=structs, profile=prm,
                            config=_cfg(aniso_auto=True)))

    # 1) 每相都补上了 6 维 size 系数
    assert on.params.aniso is not None
    assert set(on.params.aniso) == {st.name for st in structs}
    for entry in on.params.aniso.values():
        assert len(entry["size"]) == 6 and len(entry["strain"]) == 6

    # 2) registry 里真出现 6×相数 个槽（不是"开关打开等于没开"）
    reg_on = build_registry_from_config(on.config, on.params, len(structs))
    n_aniso = sum(1 for key in reg_on.labels() if ".aniso." in key)
    assert n_aniso == 6 * len(structs)
    reg_off = build_registry_from_config(off.config, off.params, len(structs))
    assert reg_on.size == reg_off.size + n_aniso

    # 3) 系数被精修过（不等于各向同性起点），计算谱真的变了
    seed = aniso_default(prm.wavelength, float(prm.X), 0.05)
    moved = any(
        abs(entry["size"][k] - seed["size"][k]) > 1e-9
        for entry in on.params.aniso.values() for k in (0, 2, 5))
    assert moved
    assert not np.allclose(on.ycalc, off.ycalc)
    # 该合成样各向同性：多 12 维自由度的代价应可忽略（不劣化 1% 以上）
    assert on.rwp <= off.rwp * 1.01

    # 4) 告警可追溯（谁被自动启用）
    assert any("自动启用" in w for w in on.warnings)


def test_auto_skips_phase_with_too_few_directions(structs, pat):
    """方向数不足的相自动跳过（告警而非抛异常）——自动模式不该让精修失败。"""
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    # 窗口只覆盖 anatase 的 004 单峰：独立晶向 << 8
    cfg = _cfg(tmin=36.8, tmax=39.0, aniso_auto=True, max_iter=4)
    res = solve(RefineInputs(pattern=pat, phases=[structs[0]], profile=prm,
                             config=cfg))
    assert any("跳过该相" in w for w in res.warnings)
    assert res.params.aniso is None


def test_explicit_config_still_hard_fails(structs, pat):
    """显式配置的相方向数不足时仍报错（硬护栏不能被 auto 软化）。"""
    iso = aniso_default(1.5406)
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        aniso={structs[0].name: iso})
    cfg = _cfg(tmin=36.8, tmax=39.0, refine_aniso=True, max_iter=4)
    with pytest.raises(ValueError, match="欠定"):
        solve(RefineInputs(pattern=pat, phases=[structs[0]], profile=prm,
                           config=cfg))


def test_recipe_only_refines_aniso_in_micro_step():
    """配方语义：aniso_auto 只在 micro 步放开，其余步把 aniso 当固定因子。"""
    micro = next(s for s in DEFAULT_STEPS if s.key == "micro")
    bg = next(s for s in DEFAULT_STEPS if s.key == "bg")
    cfg = _cfg(aniso_auto=True)
    assert micro.config_for(cfg).refine_aniso is True
    assert micro.config_for(cfg).aniso_auto is True
    assert bg.config_for(cfg).refine_aniso is False
    assert bg.config_for(cfg).aniso_auto is False


@pytest.fixture(scope="module")
def aniso_pat(structs, pat):
    """强各向异性尺寸合成谱（c 向 D=60 Å、a 向 D=200 Å），用于验证真实收益。"""
    from xinrefinement.core.dtypes import Pattern
    from xinrefinement.core.profile.forward import compute_phase_profile

    fit = solve(RefineInputs(
        pattern=pat, phases=structs,
        profile=ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu"),
        config=_cfg(refine_eta=True, refine_size=True, refine_strain=True,
                    max_iter=20)))
    prm_fit = fit.params
    truth = {"size": [1 / 200.0, 0.0, 1 / 200.0, 0.0, 0.0, 1 / 60.0],
             "strain": [1e-6, 0.0, 1e-6, 0.0, 0.0, 1e-6]}
    prm_truth = replace(prm_fit, aniso={structs[0].name: truth}, X=0.0, Y=0.0)
    tt = fit.pattern.two_theta
    sc0 = float(fit.engine.scales[0])
    y0 = compute_phase_profile(structs[0], tt, prm_fit)
    y1 = compute_phase_profile(structs[0], tt, prm_truth)
    return Pattern(two_theta=tt,
                   intensity=fit.ycalc - y0 * sc0 + y1 * sc0,
                   meta=dict(pat.meta))


def test_recipe_run_all_with_aniso_auto(structs, aniso_pat):
    """端到端：真各向异性数据上，配方 micro 步自动启用后 Rwp 明显改善。"""
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    off = solve(RefineInputs(pattern=aniso_pat, phases=structs, profile=prm,
                             config=_cfg(max_iter=20)))
    cfg = replace(_cfg(max_iter=20), aniso_auto=True)
    runner = RecipeRunner()
    res, recs = runner.run_all(RefineInputs(pattern=aniso_pat, phases=structs,
                                            profile=prm, config=cfg))
    micro = next(r for r in recs if r.key == "micro")
    assert micro.status == "done"
    assert res.params.aniso is not None
    assert res.rwp < off.rwp                      # 自动启用真的带来改善
    assert micro.rwp_after is not None and micro.rwp_after < micro.rwp_before


def test_recipe_rolls_back_when_aniso_does_not_help(structs, pat):
    """护栏：各向异性没带来改善时 micro 步整体回退（不留更差的参数）。"""
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    cfg = replace(_cfg(max_iter=4), aniso_auto=True)
    runner = RecipeRunner()
    res, recs = runner.run_all(RefineInputs(pattern=pat, phases=structs,
                                            profile=prm, config=cfg))
    micro = next(r for r in recs if r.key == "micro")
    # 该样各向同性 + 迭代预算极短 -> 判回退，且末值不劣于入参
    assert "已回退" in micro.message
    assert micro.rwp_after == pytest.approx(micro.rwp_before)
    assert res.params.aniso is None
