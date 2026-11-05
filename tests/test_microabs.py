"""v1.2.0 · Brindley 微吸收校正（按相）验收。

契约（``forward.brindley_factor`` / ``ProfileParams.microabs``）：
- 默认 None → 与 v1.1.x 逐位一致（golden 不漂移）；
- 因子 (1−e^(−μr))/(μr)，μr→0 极限 1，单调递减；
- 只乘到**对应相**的计算谱；缺相不校正；
- 两相体系：高 μ 相加校正后其 wt% 抬升（微吸收被纠正的方向）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams,
    brindley_factor,
    compute_phase_profile,
)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"


def _inputs(microabs: dict | None = None):
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False, microabs=microabs)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=3, max_iter=40, tmin=5.0, tmax=90.0)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def test_brindley_factor_values():
    assert brindley_factor(0.0) == 1.0
    assert brindley_factor(-1.0) == 1.0          # 非正 μr = 不校正
    assert brindley_factor(float("nan")) == 1.0
    # 小 μr 极限：(1-e^-x)/x ≈ 1 - x/2
    assert brindley_factor(1e-10) == pytest.approx(1.0, abs=1e-9)
    assert brindley_factor(1.0) == pytest.approx(1.0 - math.exp(-1.0))
    # 单调递减
    xs = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
    fs = [brindley_factor(x) for x in xs]
    assert all(a > b for a, b in zip(fs, fs[1:]))


def test_profile_scaled_only_for_named_phase():
    st = parse_cif(DATA_CIF / "anatase.cif")
    grid = np.linspace(10.0, 80.0, 1400)
    prm0 = ProfileParams(zero=0.0, U=0.01, V=-0.005, W=0.01, eta=0.5,
                         anode="Cu", integrated=True)
    base = compute_phase_profile(st, grid, prm0)
    f = brindley_factor(1.7)
    prm_ma = ProfileParams(**{**prm0.__dict__,
                              "microabs": {st.name: 1.7}})
    scaled = compute_phase_profile(st, grid, prm_ma)
    assert np.allclose(scaled, base * f)
    # 缺相：不校正
    prm_other = ProfileParams(**{**prm0.__dict__,
                                 "microabs": {"别的相": 1.7}})
    assert np.all(compute_phase_profile(st, grid, prm_other) == base)


def test_default_off_is_bit_identical():
    """microabs=None 与显式 {} 行为一致，golden 不漂移。"""
    a = solve(_inputs())
    b = solve(_inputs(microabs={}))
    assert a.rwp == b.rwp
    assert a.rwp == pytest.approx(3.409617, abs=0.01)


def test_microabs_raises_heavy_phase_weight():
    """高 μ 相加校正后 wt% 抬升（微吸收曾压低其表观含量的纠正方向）。"""
    st_a = parse_cif(DATA_CIF / "anatase.cif")
    base = solve(_inputs())
    ma = solve(_inputs(microabs={st_a.name: 5.0}))
    assert ma.rwp != base.rwp           # 校正确实进入了强度链
    wa0 = base.phases[0].weight_pct
    wa1 = ma.phases[0].weight_pct
    assert wa0 is not None and wa1 is not None
    assert wa1 > wa0
    assert ma.phases[0].z == base.phases[0].z   # 元数据不受影响
