"""v1.5 M3：球谐（纤维对称 → Legendre）织构 ODF。

为什么是 Legendre 而不是完整球谐
--------------------------------
Bragg–Brentano 平板 + 样品自转下，散射矢量恒沿样品法向，ODF 只依赖极角 χ。
把球谐展开 ``f = Σ C_lm Y_lm`` 对 m 求和（轴对称）后 m≠0 项全消；又因
(χ, 180°−χ) 等价（我们取 |cos α|），奇数 l 项也恒消。剩下
``T(χ) = 1 + Σ_{l even} c_l P_l(cos χ)``——即 MAUD ``Harmonic``
（``_rita_harmonic_expansion_degree`` 6/8）在本仪器几何下的**精确子空间**。

关键性质（下面逐条断言）：
* 基正交 → 条件数好、无需二阶差分光滑罚；
* ``∫P_l dΩ/4π = 0 (l ≥ 2)`` → T 的球面平均恒为 1，不存在
  「T 乘常数 ↔ 该相 scale 除常数」零空间（EWIMV 要靠末端锚定消除）；
* 系数全 0 ⇒ T≡1，与不加织构**逐位一致**（零回归）。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.params.registry import build_registry_from_config
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    TEXTURE_COEFF_BOUNDS,
    TEXTURE_N_GRID,
    ProfileParams,
    compute_phase_profile,
    default_texture_coeffs,
    default_texture_grid,
    texture_coeffs,
    texture_degrees,
    texture_factor,
    texture_factor_entry,
    texture_factor_harmonic,
    texture_model,
    texture_n_params,
)
from xinrefinement.core.refine.nonlinear import (
    RefineConfig,
    _bounds,
    _pack,
    _unpack,
)
from xinrefinement.core.refine.solve import RefineInputs, solve

DATA = Path(__file__).parent.parent / "xinrefinement" / "data"
VIRTUAL_B = Path(__file__).parent / "data" / "virtual_b"
AXIS = (0, 0, 1)


def _har(degree=4, coeffs=None, axis=AXIS):
    return {"axis": axis, "model": "harmonic", "degree": degree,
            "coeffs": list(coeffs if coeffs is not None
                           else default_texture_coeffs(degree))}


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]


@pytest.fixture(scope="module")
def synthetic(structs):
    """带人造 Legendre 织构（c2=0.45, c4=−0.25）的无噪合成谱 + 基线参数。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    cfg0 = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                        refine_size=True, refine_strain=True, n_bg=3,
                        max_iter=40, tmin=5.0, tmax=90.0)
    base = solve(RefineInputs(
        pattern=pat, phases=structs, config=cfg0,
        profile=ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")))
    prm_fit = base.params
    tt = base.pattern.two_theta
    scale0 = float(base.engine.scales[0])
    truth = [0.45, -0.25]
    y0 = compute_phase_profile(structs[0], tt, prm_fit)
    y1 = compute_phase_profile(
        structs[0], tt,
        replace(prm_fit,
                texture={structs[0].name: _har(4, truth)}))
    y_syn = base.ycalc - y0 * scale0 + y1 * scale0
    pat_syn = Pattern(two_theta=tt, intensity=y_syn, meta=dict(pat.meta))
    return pat_syn, prm_fit, truth


# --------------------------------------------------------------------------
# 1. 基函数本身
# --------------------------------------------------------------------------
def test_degrees_only_even_and_bounded():
    assert texture_degrees(2) == (2,)
    assert texture_degrees(4) == (2, 4)
    assert texture_degrees(8) == (2, 4, 6, 8)
    # 阶 10 是允许的上限（MAUD 实测用到 10：样 3 萤石、样 1 白云石）
    assert texture_degrees(10) == (2, 4, 6, 8, 10)
    for bad in (0, 1, 3, 7, 12, 14):
        with pytest.raises(ValueError):
            texture_degrees(bad)


def test_spherical_average_is_one():
    """∫T dΩ / 4π ≡ 1 —— 尺度零空间天然消除（EWIMV 需靠锚定才行）。"""
    chi = np.linspace(0.0, np.pi, 40001)
    w = np.sin(chi)
    for degree in (4, 6, 8):
        n = len(texture_degrees(degree))
        coeffs = [(-1) ** i * 0.35 for i in range(n)]
        t = texture_factor_harmonic(np.degrees(chi), coeffs)
        avg = float(np.trapezoid(t * w, chi) / np.trapezoid(w, chi))
        assert abs(avg - 1.0) < 1e-6, (degree, avg)


def test_zero_coeffs_are_exactly_one():
    chi = np.array([0.0, 12.3, 45.0, 89.9, 90.0])
    for degree in (4, 6, 8):
        t = texture_factor_harmonic(chi, default_texture_coeffs(degree))
        assert np.array_equal(t, np.ones_like(chi))


def test_floor_truncation_keeps_positive():
    """极端系数下也不出现非正强度（负 ODF 截断）。"""
    chi = np.linspace(0.0, 90.0, 181)
    t = texture_factor_harmonic(chi, [0.8, -0.8, 0.8, -0.8])
    assert np.all(t > 0.0)


# --------------------------------------------------------------------------
# 2. 模型分派与向后兼容
# --------------------------------------------------------------------------
def test_model_dispatch_and_backward_compat():
    assert texture_model({"axis": AXIS, "grid": default_texture_grid()}) == "ewimv"
    assert texture_model({"axis": AXIS, "grid": [1.0] * 19}) == "ewimv"
    assert texture_model({"axis": AXIS, "degree": 4}) == "harmonic"
    assert texture_model({"axis": AXIS, "coeffs": [0.1]}) == "harmonic"
    assert texture_model({"axis": AXIS, "model": "Harmonic"}) == "harmonic"
    assert texture_model({"axis": AXIS, "model": " EWIMV "}) == "ewimv"


def test_ewimv_dispatch_bitwise_identical():
    """走 entry 分派后 EWIMV 数值必须与旧 texture_factor 逐位一致。"""
    grid = [1.0 + 0.13 * i for i in range(TEXTURE_N_GRID)]
    chi = np.linspace(0.0, 90.0, 401)
    entry = {"axis": AXIS, "grid": grid}
    a = texture_factor_entry(chi, entry)
    b = texture_factor(chi, grid)
    assert np.array_equal(a, b)
    assert texture_n_params(entry) == TEXTURE_N_GRID
    assert texture_n_params(_har(6)) == 3


def test_coeffs_pad_truncate():
    assert texture_coeffs({"degree": 8, "coeffs": [0.1]}) == [0.1, 0.0, 0.0, 0.0]
    assert texture_coeffs({"degree": 4, "coeffs": [0.1, 0.2, 0.3]}) == [0.1, 0.2]
    assert texture_coeffs({}) == [0.0, 0.0]


# --------------------------------------------------------------------------
# 3. 引擎接线：前向 / pack / bounds 三方一致
# --------------------------------------------------------------------------
def test_forward_no_texture_bitwise_unchanged(structs):
    grid = np.linspace(10.0, 90.0, 3001)
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    y0 = compute_phase_profile(structs[0], grid, prm)
    y1 = compute_phase_profile(
        structs[0], grid,
        replace(prm, texture={structs[0].name: _har(4)}))
    assert np.allclose(y0, y1, rtol=0.0, atol=1e-9)


def test_forward_harmonic_changes_profile(structs):
    grid = np.linspace(10.0, 90.0, 3001)
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    y0 = compute_phase_profile(structs[0], grid, prm)
    y1 = compute_phase_profile(
        structs[0], grid,
        replace(prm, texture={structs[0].name: _har(4, [0.6, 0.0])}))
    assert not np.allclose(y0, y1)


def test_registry_pack_matches_engine_harmonic(structs):
    """registry 与旧 _pack/_unpack/_bounds 在球谐槽位上逐位一致。"""
    prm = ProfileParams(U=0.1, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        texture={structs[0].name: _har(6, [0.2, -0.1, 0.05])})
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_size=True,
                       refine_texture=True)
    reg = build_registry_from_config(cfg, prm, 2)
    assert np.array_equal(reg.pack(prm), _pack(prm, cfg, 2))
    lo_r, hi_r = reg.bounds()
    lo_o, hi_o = _bounds(cfg, 2, 0, 0, [TEXTURE_COEFF_BOUNDS] * 3)
    assert np.array_equal(lo_r, lo_o) and np.array_equal(hi_r, hi_o)
    prm_r, _, _ = reg.unpack(reg.pack(prm), prm)
    prm_o, _ = _unpack(_pack(prm, cfg, 2), prm, cfg, 2)
    assert prm_r.texture == prm_o.texture
    assert prm_r.Y == prm_o.Y


def test_registry_labels_readable(structs):
    prm = ProfileParams(U=0.1, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        texture={structs[0].name: _har(6)})
    reg = build_registry_from_config(
        RefineConfig(refine_texture=True, refine_zero=False, refine_uvw=False),
        prm, 2)
    labels = reg.labels()
    assert labels == [f"phase[{structs[0].name}].texture.c{k}"
                      for k in (2, 4, 6)]


def test_bounds_clamp_coefficients(structs):
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, texture={structs[0].name: _har(4)})
    cfg = RefineConfig(refine_zero=False, refine_uvw=False, refine_texture=True)
    reg = build_registry_from_config(cfg, prm, 2)
    x = np.array([9.9, -9.9])       # 远超边界
    prm2, _, _ = reg.unpack(x, prm)
    assert prm2.texture[structs[0].name]["coeffs"] == [
        TEXTURE_COEFF_BOUNDS[1], TEXTURE_COEFF_BOUNDS[0]]


# --------------------------------------------------------------------------
# 4. 端到端：能回收人造织构
# --------------------------------------------------------------------------
def test_end_to_end_recovers_harmonic(structs, synthetic):
    pat_syn, prm_fit, truth = synthetic
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                       refine_size=False, refine_strain=False,
                       refine_texture=True, n_bg=3, max_iter=40,
                       tmin=5.0, tmax=90.0)
    off = solve(RefineInputs(
        pattern=pat_syn, phases=structs, config=cfg,
        profile=replace(prm_fit, texture=None)))
    tex = {structs[0].name: _har(4)}
    on = solve(RefineInputs(
        pattern=pat_syn, phases=structs, config=cfg,
        profile=replace(prm_fit, texture=tex)))
    # 人造的既有织构被关掉时 Rwp 明显劣化，开了就能压回来
    assert off.rwp > on.rwp
    c = on.params.texture[structs[0].name]["coeffs"]
    assert abs(c[0] - truth[0]) < 0.35, c
    assert abs(c[1] - truth[1]) < 0.35, c


def test_harmonic_beats_ewimv_on_smooth_truth(structs, synthetic):
    """真值本就光滑：低维球谐至少不劣于 19 维离散网格（且参数少一个量级）。"""
    pat_syn, prm_fit, _truth = synthetic
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                       refine_size=False, refine_strain=False,
                       refine_texture=True, n_bg=3, max_iter=40,
                       tmin=5.0, tmax=90.0)
    r_h = solve(RefineInputs(
        pattern=pat_syn, phases=structs, config=cfg,
        profile=replace(prm_fit, texture={structs[0].name: _har(4)}))).rwp
    r_e = solve(RefineInputs(
        pattern=pat_syn, phases=structs, config=cfg,
        profile=replace(prm_fit, texture={
            structs[0].name: {"axis": AXIS,
                              "grid": default_texture_grid()}}))).rwp
    assert r_h <= r_e * 1.02, (r_h, r_e)


# --------------------------------------------------------------------------
# 5. 可辨识性护栏
# --------------------------------------------------------------------------
def test_insufficient_buckets_raises(structs):
    """窗口只覆盖极少数 χ 时球谐系数不可辨识——必须报错而非静默出结果。"""
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, anode="Cu",
                        texture={structs[0].name: _har(8)})
    cfg = RefineConfig(refine_zero=False, refine_uvw=False,
                       refine_texture=True, tmin=25.0, tmax=25.6, n_bg=3)
    with pytest.raises(ValueError, match="球谐织构欠定|欠定"):
        solve(RefineInputs(
            pattern=Pattern(two_theta=np.linspace(25.0, 25.6, 61),
                            intensity=np.ones(61)),
            phases=structs, config=cfg, profile=prm))
