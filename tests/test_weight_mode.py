"""v1.2.0 · 定权模式（``weight_mode``）验收（借鉴 MAUD getWeight 4 模式）。

契约（见 ``nonlinear.effective_sigma``）：
- 默认 ``sqrt`` 与 v1.1.x **逐位一致**（golden 不漂移）；
- ``file`` 读谱图 ``meta["sigma"]``，缺/坏回退 sqrt 不报错；
- ``unit`` / ``1/y`` 改变权重且残差/Rwp 同口径；
- 非法模式显式报错。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig, effective_sigma
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"


def _inputs(weight_mode: str = "sqrt", meta_sigma: np.ndarray | None = None):
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    if meta_sigma is not None:
        meta = dict(pat.meta)
        meta["sigma"] = meta_sigma
        pat = Pattern(two_theta=pat.two_theta, intensity=pat.intensity, meta=meta)
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=3, max_iter=40, tmin=5.0, tmax=90.0,
                       weight_mode=weight_mode)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def test_default_sqrt_bit_identical():
    """默认与显式 sqrt 必须逐位一致（回归保护，golden 不漂移）。"""
    r_def = solve(_inputs())
    r_sqrt = solve(_inputs("sqrt"))
    assert r_def.rwp == r_sqrt.rwp
    assert r_def.params == r_sqrt.params
    # 与 v1.1.x golden 同档
    assert r_def.rwp == pytest.approx(3.409617, abs=0.01)


def test_effective_sigma_modes():
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    yo = pat.intensity
    cfg0 = RefineConfig()
    # sqrt = 现行为
    assert np.allclose(effective_sigma(cfg0, pat), np.sqrt(np.maximum(yo, 1.0)))
    # unit = 常数权
    assert np.all(effective_sigma(RefineConfig(weight_mode="unit"), pat) == 1.0)
    # 1/y：σ=y（夹 ≥1）
    assert np.allclose(effective_sigma(RefineConfig(weight_mode="1/y"), pat),
                       np.maximum(yo, 1.0))
    # 显式 sigma 永远优先
    custom = np.full_like(yo, 2.0)
    assert np.all(effective_sigma(RefineConfig(sigma=custom,
                                               weight_mode="unit"), pat) == 2.0)


def test_file_mode_reads_meta_and_falls_back():
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    yo = pat.intensity
    sig = 1.0 + 0.01 * np.sqrt(np.maximum(yo, 1.0))
    got = effective_sigma(RefineConfig(weight_mode="file"),
                          Pattern(two_theta=pat.two_theta,
                                  intensity=yo, meta={"sigma": sig}))
    assert np.allclose(got, sig)
    # 缺 sigma → 回退 sqrt（宽松加载，不报错）
    got2 = effective_sigma(RefineConfig(weight_mode="file"), pat)
    assert np.allclose(got2, np.sqrt(np.maximum(yo, 1.0)))
    # 形状不符 → 回退
    got3 = effective_sigma(RefineConfig(weight_mode="file"),
                           Pattern(two_theta=pat.two_theta, intensity=yo,
                                   meta={"sigma": sig[:-2]}))
    assert np.allclose(got3, np.sqrt(np.maximum(yo, 1.0)))


def test_unit_and_inv_y_solve_run():
    """非默认模式端到端可跑、Rwp 有限、success=True。"""
    for mode in ("unit", "1/y", "file"):
        res = solve(_inputs(mode))
        assert res.success, mode
        assert np.isfinite(res.rwp) and res.rwp < 50.0, mode


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="weight_mode"):
        effective_sigma(RefineConfig(weight_mode="bogus"),
                        load_pattern(VIRTUAL_B / "v50_wide.xy"))


# ---- v1.3：theoreticalWeights（σ 取计算值） ----------------------------

def test_effective_sigma_theoretical():
    """theoretical：σ=√max(ycalc,1)；省略 ycalc 时用观测值引导。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    cfg = RefineConfig(weight_mode="theoretical")
    yc = np.full(pat.intensity.size, 400.0)
    got = effective_sigma(cfg, pat, ycalc=yc)
    assert np.allclose(got, 20.0)
    # 引导语义：无 ycalc → √max(y_o,1)
    got0 = effective_sigma(cfg, pat)
    assert np.allclose(got0, np.sqrt(np.maximum(pat.intensity, 1.0)))


def test_theoretical_resolve_writes_sigma():
    """solve() 入口把 theoretical 解析成固定 cfg.sigma（引导一次）。"""
    res = solve(_inputs("theoretical"))
    assert res.config.sigma is not None
    assert res.config.weight_mode == "theoretical"
    assert np.all(res.config.sigma >= 1.0)
    assert any("theoreticalWeights" in w for w in res.warnings)


def test_theoretical_solve_runs_and_differs():
    """theoretical 端到端可跑；定权改变参数轨迹（Rwp 与 sqrt 模式不同）。"""
    r_th = solve(_inputs("theoretical"))
    r_sq = solve(_inputs("sqrt"))
    assert r_th.success and np.isfinite(r_th.rwp) and r_th.rwp < 50.0
    assert r_th.rwp != pytest.approx(r_sq.rwp, rel=1e-9)


def test_theoretical_explicit_sigma_wins():
    """显式 sigma 仍最高优先（解析跳过，契约不破坏）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    custom = np.full_like(pat.intensity, 5.0)
    cfg = RefineConfig(weight_mode="theoretical", sigma=custom)
    assert np.all(effective_sigma(cfg, pat) == 5.0)
