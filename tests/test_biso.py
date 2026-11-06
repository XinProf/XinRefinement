"""v1.4 任务 #18：每相各向同性温度因子增量 ΔB_iso 精修。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.params.registry import build_registry_from_config
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams, compute_phase_profile)
from xinrefinement.core.refine import nonlinear as nl
from xinrefinement.core.refine.recipe import DEFAULT_STEPS
from xinrefinement.core.refine.solve import RefineInputs, solve

VB = Path("tests/data/virtual_b")
DATA = Path("xinrefinement/data")


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"),
            parse_cif(DATA / "rutile.cif")]


def _prm(**kw):
    return ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True, **kw)


def test_forward_biso_is_debye_waller_factor(structs):
    """ΔB_iso 与全局 bfactor 同为 exp(−B/(2d²))，且可逐相独立。"""
    st = structs[0]
    grid = np.linspace(10.0, 90.0, 4001)
    base = compute_phase_profile(st, grid, _prm())
    one = compute_phase_profile(st, grid, _prm(b_iso={st.name: 1.5}))
    # 全局 bfactor=1.5 应逐位等价
    glob = compute_phase_profile(st, grid, _prm(bfactor=1.5))
    assert np.allclose(one, glob, rtol=0, atol=1e-12)
    assert (one < base).any()                 # 高角被压低
    assert one[0] == pytest.approx(base[0], rel=1e-6)   # 低角几乎不变
    # 另一相不受影响
    other = structs[1]
    assert np.allclose(compute_phase_profile(other, grid,
                                             _prm(b_iso={st.name: 1.5})),
                       compute_phase_profile(other, grid, _prm()))


def test_pack_unpack_bounds_match_registry(structs):
    """三条旧 API 与声明式 registry 逐位对拍（含 X/Y 末端倒读）。"""
    prm = _prm(b_iso={st.name: v for st, v in zip(structs, (0.4, 1.2))})
    cfg = nl.RefineConfig(refine_zero=True, refine_uvw=True,
                          refine_biso=True, refine_size=True,
                          refine_strain=True)
    reg = build_registry_from_config(cfg, prm, len(structs))
    x_reg = reg.pack(prm)
    x_old = nl._pack(prm, cfg, len(structs))
    assert np.array_equal(x_reg, x_old)
    lo_r, hi_r = reg.bounds()
    lo_o, hi_o = nl._bounds(cfg, len(structs), 0, 0, 0, 0, 2)
    assert np.array_equal(lo_r, lo_o) and np.array_equal(hi_r, hi_o)
    p_reg, _cell, _po = reg.unpack(x_reg, prm)
    p_old, _c2 = nl._unpack(x_old, prm, cfg, len(structs))
    assert p_reg.b_iso == p_old.b_iso
    assert p_reg.Y == pytest.approx(p_old.Y)
    assert f"phase[{structs[0].name}].B_iso" in reg.labels()


def test_solve_seeds_zeros_and_warns(structs):
    """开启时缺相补 0；未开启时 prm.b_iso 保持原样（golden 零回归）。"""
    pat = load_pattern(VB / "v50_wide.xy")
    cfg = nl.RefineConfig(n_bg=3, max_iter=1, tmin=5.0, tmax=90.0,
                          refine_biso=True)
    res = solve(RefineInputs(pat, structs, _prm(), cfg))
    assert set(res.params.b_iso) == {st.name for st in structs}
    assert any("ΔB_iso" in w for w in res.warnings)
    off = solve(RefineInputs(pat, structs, _prm(),
                             nl.RefineConfig(n_bg=3, max_iter=1)))
    assert off.params.b_iso is None


def test_recipe_b_step_opt_in(structs):
    """B 步已落地，但只在调用方显式开启时精修 ΔB_iso。"""
    by = {s.key: s for s in DEFAULT_STEPS}
    assert by["B"].available is True
    # v1.4 #17 落地后 xyz 步也标记为可用，但仍需显式 opt-in（运行期跳过）
    assert [s.key for s in DEFAULT_STEPS if not s.available] == []
    assert by["xyz"].available is True
    cfg_on = nl.RefineConfig(refine_biso=True)
    assert by["B"].config_for(cfg_on).refine_biso is True
    assert by["micro"].config_for(cfg_on).refine_biso is False
    assert by["B"].config_for(nl.RefineConfig()).refine_biso is False


def test_recovers_injected_biso(structs):
    """合成数据注入 ΔB=1.5，逐相精修应回收到 ±10%。"""
    pat = load_pattern(VB / "v50_wide.xy")
    base_cfg = nl.RefineConfig(refine_zero=True, refine_uvw=True,
                               n_bg=3, max_iter=30, tmin=5.0, tmax=90.0)
    base = solve(RefineInputs(pat, structs, _prm(), base_cfg))
    name = structs[0].name
    truth = replace(base.params, b_iso={name: 1.5})
    tt = base.pattern.two_theta
    b0 = compute_phase_profile(structs[0], tt, base.params)
    b1 = compute_phase_profile(structs[0], tt, truth)
    s0 = float(base.engine.scales[0])
    syn = Pattern(two_theta=tt,
                  intensity=base.ycalc - b0 * s0 + b1 * s0,
                  meta=dict(pat.meta))
    cfg = nl.RefineConfig(refine_biso=True, n_bg=3, max_iter=40,
                          tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(syn, structs, base.params, cfg))
    # 不含 B 校正的基线应明显更差
    off = solve(RefineInputs(syn, structs, base.params,
                             nl.RefineConfig(n_bg=3, max_iter=1)))
    assert got.rwp < off.rwp - 1.0
    assert got.params.b_iso[name] == pytest.approx(1.5, rel=0.10)


def test_biso_bound_warning(structs):
    """真值超出上界时撞界，solve 必须提示「模型误差被 B 吸收」。

    v1.4 实样基准里 4/7 样把某些相顶到 6 Å²，且正是 PO/织构该修的相；
    这条告警是防止把过拟合参数当成物理温度因子的最后一道护栏。
    """
    pat = load_pattern(VB / "v50_wide.xy")
    base_cfg = nl.RefineConfig(refine_zero=True, refine_uvw=True,
                               n_bg=3, max_iter=30, tmin=5.0, tmax=90.0)
    base = solve(RefineInputs(pat, structs, _prm(), base_cfg))
    name = structs[0].name
    truth = replace(base.params, b_iso={name: 12.0})
    tt = base.pattern.two_theta
    b0 = compute_phase_profile(structs[0], tt, base.params)
    b1 = compute_phase_profile(structs[0], tt, truth)
    s0 = float(base.engine.scales[0])
    syn = Pattern(two_theta=tt,
                  intensity=base.ycalc - b0 * s0 + b1 * s0,
                  meta=dict(pat.meta))
    res = solve(RefineInputs(syn, structs, base.params,
                             nl.RefineConfig(refine_biso=True, n_bg=3,
                                             max_iter=40, tmin=5.0,
                                             tmax=90.0)))
    assert res.params.b_iso[name] == pytest.approx(nl.BISO_BOUNDS[1], abs=1e-3)
    assert any("顶到上界" in w for w in res.warnings)
