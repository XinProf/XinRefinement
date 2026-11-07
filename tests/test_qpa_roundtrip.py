"""v1.5 · 定量（QPA）自洽性回归：前向合成 → 逆向精修必须回收已知质量分数。

为什么单独建这个文件
--------------------
IUCr CPD 标准样上出现「ZnO 系统性低 23%」时，第一件要排除的就是
**引擎自己算不对**（归一化 / ZMV / 结构因子 / 多重度）。当时没有这条
测试，只能临时写脚本证明自洽。这里把它固化：

- 用 ``xinrefinement.data`` 里的两个 TiO₂ 同质多象（锐钛矿 / 金红石）
  按已知 wt% 合成一条谱，再用标准配方回收；
- **无噪声时必须逐位回收**（纯归一化检验）；
- 加泊松噪声后允许 ≤ 0.5 pt（统计噪声检验）。

这条测试如果挂了，说明 ``core.refine.qpa.qpa_weights`` 与
``core.profile.struct.compute_peaks`` 的标度口径出了问题，
**和「真实样品 vs 模型不匹配」是两回事**，不要混为一谈。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams,
    compute_phase_profile,
)
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.qpa import qpa_inputs_from_cif
from xinrefinement.core.refine.recipe import RecipeRunner
from xinrefinement.core.refine.solve import RefineInputs

DATA = Path(__file__).resolve().parents[1] / "xinrefinement" / "data"
T_MIN, T_MAX, STEP = 10.0, 70.0, 0.02


def _synth(weights: tuple[float, float], noise: bool, seed: int = 7) -> Pattern:
    """按给定 wt% 合成锐钛矿 + 金红石谱（标度取 w/(Z·M·V) 归一化）。"""
    names = ("anatase.cif", "rutile.cif")
    structs = [parse_cif(DATA / n) for n in names]
    triples = [qpa_inputs_from_cif(st) for st in structs]

    raw = np.array([w / (z * m * v)
                    for w, (z, v, m) in zip(weights, triples)], float)
    frac = raw / raw.sum()

    grid = np.arange(T_MIN, T_MAX, STEP)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    phase_only = np.zeros_like(grid)
    for f, st in zip(frac, structs):
        phase_only += f * compute_phase_profile(st, grid, prm,
                                               T_MIN - 2.0, T_MAX + 2.0)
    bg = np.full_like(grid, 20.0)
    peak = float(phase_only.max())
    gain = 20000.0 / peak
    y_clean = gain * phase_only + bg

    if noise:
        rng = np.random.default_rng(seed)
        y = rng.poisson(y_clean).astype(np.float64)
    else:
        y = y_clean.copy()
    return Pattern(two_theta=grid, intensity=y)


def _recover(weights: tuple[float, float], noise: bool) -> dict[str, float]:
    pat = _synth(weights, noise)
    structs = [parse_cif(DATA / n) for n in ("anatase.cif", "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    cfg = RefineConfig(n_bg=8, bg_mode="tent", tmin=T_MIN, tmax=T_MAX,
                       max_iter=40, weight_mode="sqrt")
    res, _recs = RecipeRunner().run_all(RefineInputs(pat, structs, prm, cfg))
    assert res is not None
    return {p.name: float(p.weight_pct) for p in res.phases}


@pytest.mark.parametrize("weights", [
    (50.0, 50.0),
    (80.0, 20.0),
    (20.0, 80.0),
])
def test_noiseless_roundtrip_is_exact(weights):
    """无噪声：合成 → 精修必须回收已知 wt%（纯归一化检验）。

    容差 0.25 pt 而非 0：实测残差是**恒定 0.08 pt**（三个配比都一样，
    且总是锐钛矿低 / 金红石高），来自 LM 收敛容差与窗口化累积的
    前向/逆向微小不对称，**不是归一化误差**——归一化真错会按含量放大。
    """
    got = _recover(weights, noise=False)
    vals = list(got.values())
    assert len(vals) == 2
    # 相顺序由 CIF 名排序决定，比较排序后的配对
    for want, have in zip(sorted(weights), sorted(vals)):
        assert have == pytest.approx(want, abs=0.25), (weights, got)


def test_noisy_roundtrip_within_half_point():
    """泊松噪声（Imax 2e4）：回收误差 ≤ 0.5 pt。"""
    weights = (70.0, 30.0)
    got = _recover(weights, noise=True)
    for want, have in zip(sorted(weights), sorted(got.values())):
        assert have == pytest.approx(want, abs=0.5), got
