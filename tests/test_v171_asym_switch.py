"""v1.7 结论七：``RefineConfig.refine_asym`` 在配方路径上必须是真开关。

改造前 ``RefineStep.config_for`` 写死 ``refine_asym=(self.key == "profile")``，
完全不看 ``cfg.refine_asym``，所以用户传 ``False`` 也照样精修 ——
2026-11-06 做 IUCr CPD 对照时实测「开/不开两次结果 Rwp 相同到 1e-11」
才发现该字段在 ``RecipeRunner`` 路径上形同虚设。

现改为**三态**：
``None``（默认）= 由配方决定（profile 步自动开，裸 ``solve`` 视为关），
``True`` / ``False`` = 强制开 / 强制关，配方路径也遵守。
默认 ``None`` 保证既有数值路径逐位不变。

覆盖：
1. 默认 ``None``：只有 profile 步开 asym，其余步关（与改造前一致）；
2. 显式 ``False``：所有步都关（修复点）；
3. 显式 ``True``：所有步都开；
4. 端到端：``run_step`` 走 profile 步，显式 ``False`` 时 ``asym`` 严格不动。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import (
    DEFAULT_STEPS, RecipeRunner)
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"

PROFILE_STEP = next(s for s in DEFAULT_STEPS if s.key == "profile")
ZERO_STEP = next(s for s in DEFAULT_STEPS if s.key == "zero")


def _cfg(**kw) -> RefineConfig:
    kw.setdefault("max_iter", 3)
    return RefineConfig(n_bg=3, bg_mode="tent", tmin=5.0, tmax=90.0, **kw)


def _prm() -> ProfileParams:
    return ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True)


def _base(cfg: RefineConfig):
    """同一份虚拟谱 + 默认配置跑一次裸 solve，作为配方步的初值/对照。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    base = solve(RefineInputs(pat, phases, _prm(), _cfg(max_iter=20)))
    return RefineInputs(pat, phases, _prm(), cfg), base


def test_default_none_keeps_historical_behaviour() -> None:
    """默认 None：profile 步开 asym，其余步关 —— 与改造前逐位等价。"""
    cfg = _cfg()
    assert cfg.refine_asym is None
    assert PROFILE_STEP.config_for(cfg).refine_asym is True
    for step in DEFAULT_STEPS:
        if step.key != "profile":
            assert step.config_for(cfg).refine_asym is False


def test_explicit_false_closes_asym_on_every_step() -> None:
    """修复点：显式 False 必须能关掉，含 profile 步。"""
    cfg = _cfg(refine_asym=False)
    for step in DEFAULT_STEPS:
        assert step.config_for(cfg).refine_asym is False


def test_explicit_true_opens_asym_on_every_step() -> None:
    """显式 True 是「强制开」，连 zero 步也开。"""
    cfg = _cfg(refine_asym=True)
    for step in DEFAULT_STEPS:
        assert step.config_for(cfg).refine_asym is True


def test_recipe_profile_step_honours_explicit_off() -> None:
    """端到端：显式 False 时 profile 步不得移动 asym。

    给初值一个非零 asym（0.08），若开关失效该值必然被 LM 拉走。
    """
    cfg = _cfg(refine_asym=False)
    inputs, base = _base(cfg)
    base = replace(base, params=replace(base.params, asym=0.08))
    res, rec = RecipeRunner().run_step(PROFILE_STEP, inputs, base)
    assert rec.status == "done"
    assert res.params.asym == 0.08
    # 反证：峰形其余自由度确实动了，排除「整步没跑」
    assert (res.params.W != base.params.W
            or res.params.eta != base.params.eta
            or res.params.U != base.params.U)


def test_solve_path_still_treats_none_as_off() -> None:
    """裸 solve 路径：None 与 False 必须逐位一致（None 视为关）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    ra = solve(RefineInputs(pat, phases, _prm(), _cfg()))
    rb = solve(RefineInputs(pat, phases, _prm(), _cfg(refine_asym=False)))
    assert ra.rwp == rb.rwp
    assert ra.rexp == rb.rexp
    assert ra.params.asym == rb.params.asym
    assert np.array_equal(ra.ycalc, rb.ycalc)
