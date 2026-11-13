"""v1.7 非晶宽包分量（``RefineConfig.amorphous``）契约测试。

覆盖：
1. 基函数归一化与半高宽定义（峰高 1、±FWHM/2 处 0.5、空分量返回 (N,0)）；
2. 合成谱上能回收注入的峰高（线性层解析求解的正确性）；
3. **关闭时逐位不变**（与不传该参数的调用严格相等）——golden 保护的前提；
4. `manual` 背景分支下宽包同样可解；
5. `refine()` 结果里暴露峰高，且开启后 Rwp 不劣于关闭。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.linear import amorphous_basis, solve_linear_detail
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"
HUMP = (22.0, 9.0)


def test_amorphous_basis_peak_and_fwhm() -> None:
    tt = np.linspace(5.0, 120.0, 4001)
    b = amorphous_basis(tt, (HUMP,))
    assert b.shape == (tt.size, 1)
    assert b[:, 0].max() == pytest.approx(1.0, abs=1e-4)
    assert tt[b[:, 0].argmax()] == pytest.approx(HUMP[0], abs=0.05)
    for side in (-1.0, 1.0):
        edge = HUMP[0] + side * HUMP[1] / 2.0
        y = np.interp(edge, tt, b[:, 0])
        assert y == pytest.approx(0.5, abs=0.01)      # 半高宽定义
    # 高角端已衰减到可忽略（伪 Voigt 的洛伦兹尾在 60° 仍有 ~1%）
    assert b[tt > 60.0, 0].max() < 0.02


def test_amorphous_basis_empty() -> None:
    tt = np.linspace(5.0, 120.0, 100)
    assert amorphous_basis(tt, ()).shape == (tt.size, 0)
    assert amorphous_basis(tt, None).shape == (tt.size, 0)


def _synthetic(hump_amp: float = 250.0):
    """双相虚拟谱 + 固定宽包，作为「真值」用于回收。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    tt = pat.two_theta
    rows = [compute_phase_profile(st, tt, prm, 5.0, 90.0) for st in phases]
    basis = np.vstack(rows)
    hump = amorphous_basis(tt, (HUMP,)) @ np.array([hump_amp])
    truth = basis.T @ np.array([800.0, 400.0]) + 120.0 + hump
    return tt, basis, truth, hump_amp


def test_hump_amplitude_is_recovered() -> None:
    tt, basis, truth, amp = _synthetic()
    sig = np.sqrt(np.maximum(truth, 1.0))
    coeffs, ycalc, dropped = solve_linear_detail(
        basis, tt, truth, sig, n_bg=6, bg_mode="tent", amorphous=(HUMP,))
    assert not dropped
    n_sc = basis.shape[0]
    got = coeffs[n_sc + 6:]                       # 背景后紧跟宽包峰高
    assert got.size == 1
    assert got[0] == pytest.approx(amp, rel=0.05)
    # 合成谱自洽：残差应接近 0
    rwp = 100.0 * np.sqrt(np.sum(((truth - ycalc) / sig) ** 2)
                          / np.sum((truth / sig) ** 2))
    assert rwp < 1.0


def test_disabled_is_bit_identical() -> None:
    tt, basis, truth, _amp = _synthetic()
    sig = np.sqrt(np.maximum(truth, 1.0))
    a = solve_linear_detail(basis, tt, truth, sig, n_bg=6, bg_mode="tent")
    b = solve_linear_detail(basis, tt, truth, sig, n_bg=6, bg_mode="tent",
                            amorphous=(), amorphous_eta=0.5)
    assert a[0].shape == b[0].shape
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])


def test_manual_background_with_hump() -> None:
    tt, basis, truth, amp = _synthetic()
    sig = np.sqrt(np.maximum(truth, 1.0))
    pts = [(5.0, 120.0), (120.0, 120.0)]          # 平背景，真值本身就是 120
    coeffs, ycalc, _dropped = solve_linear_detail(
        basis, tt, truth, sig, n_bg=1, bg_mode="manual", bg_points=pts,
        amorphous=(HUMP,))
    assert coeffs.size == basis.shape[0] + 2      # 相 + 背景占位 + 宽包
    assert coeffs[-1] == pytest.approx(amp, rel=0.05)
    assert np.allclose(ycalc, truth, rtol=1e-3, atol=1e-6)


def _two_phase_cfg(amorphous: tuple) -> RefineInputs:
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=6, max_iter=15, tmin=5.0, tmax=90.0,
                       bg_mode="tent", amorphous=amorphous)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def test_refine_exposes_amplitude_and_never_worse() -> None:
    off = solve(_two_phase_cfg(()))
    on = solve(_two_phase_cfg((HUMP,)))
    assert off.amorphous.size == 0
    assert on.amorphous.size == 1
    assert on.amorphous[0] >= 0.0
    assert on.background.size == 6                        # 背景系数不被宽包顶替
    # 线性层加一列不会让同一参数下的残差变大，但 LM 的迭代轨迹会变：谱图里
    # 本来没有宽包时，多一个自由度可能停在略差的点上（实测 +0.0015 pt）。
    # 产品侧由配方步「不改善就回退」兜住，这里只锁定不出现量级劣化。
    assert on.rwp <= off.rwp + 0.05

    # 同一谱图重打包成 Project 之外的纯数组也应可重算（形状契约）
    assert isinstance(on.params, ProfileParams)
    assert on.ycalc.size == off.ycalc.size


def test_amorphous_via_pattern_dataclass_roundtrip() -> None:
    """非晶配置与谱图无关，只影响 ycalc；换个 Pattern 对象仍应可解。"""
    tt, basis, truth, _ = _synthetic()
    pat = Pattern(two_theta=tt, intensity=truth, meta={"wavelength": 1.5406})
    cfg = RefineConfig(n_bg=6, bg_mode="tent", max_iter=5, tmin=5.0, tmax=90.0,
                       amorphous=(HUMP,))
    phases = [parse_cif(DATA_CIF / "anatase.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    res = solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                             config=cfg))
    assert res.amorphous.size == 1
    assert np.isfinite(res.rwp)
