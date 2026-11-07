"""v1.5 M5（P4）：Caglioti 角依赖基 `tan` / `d`。

三个硬约束：
1. **默认 `tan` 与历史逐位相同**（golden 挂在它上面）；
2. `d` 基在 2θ→180° **有界**（tan 基发散，这是我们高角展宽失配的候选根因）；
3. 换基必须有可用的起点迁移（`convert_width_basis`），否则精修从错误
   起点出发，比较结果无意义。
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from xinrefinement.core.profile.forward import (
    ProfileParams,
    caglioti_2theta,
    caglioti_d,
    convert_width_basis,
    width_function,
)

LAM = 1.5406


def test_default_basis_is_tan_and_bit_identical():
    prm = ProfileParams(U=0.03, V=-0.01, W=0.02)
    assert prm.width_basis == "tan"
    ref = caglioti_2theta(0.03, -0.01, 0.02)
    got = width_function(prm)
    for pos in (5.0, 17.3, 40.0, 89.9, 120.0):
        assert got(pos) == ref(pos)          # 逐位，不是 approx


def test_d_basis_differs_from_tan():
    prm_d = ProfileParams(U=0.03, V=-0.01, W=0.02, width_basis="d")
    prm_t = ProfileParams(U=0.03, V=-0.01, W=0.02)
    assert width_function(prm_d)(30.0) != width_function(prm_t)(30.0)


def test_d_basis_is_bounded_at_high_angle():
    """2θ→180° 时 x=2sinθ/λ 饱和于 2/λ，tan 基则发散。"""
    tan_fn = caglioti_2theta(0.2, 0.0, 0.02)
    d_fn = caglioti_d(LAM, 0.2, 0.0, 0.02)
    w_tan_120, w_tan_179 = tan_fn(120.0), tan_fn(179.0)
    w_d_120, w_d_179 = d_fn(120.0), d_fn(179.0)
    assert w_tan_179 > 3.0 * w_tan_120          # tan 基爆掉
    assert w_d_179 < 1.6 * w_d_120              # d 基只温和增长
    # 解析上界：FWHM² ≤ 0.2·(2/1.5406)² + 0.02
    assert w_d_179 ** 2 <= 0.2 * (2.0 / LAM) ** 2 + 0.02 + 1e-9


@pytest.mark.parametrize("tmax", [90.0, 120.0])
def test_convert_gives_usable_starting_point(tmax):
    """tan → d 换算是**起点迁移**，窗口内形状应大体一致（不是恒等）。"""
    U, V, W = 0.05, -0.02, 0.015
    a, b, c = convert_width_basis(U, V, W, LAM, 5.0, tmax, frm="tan", to="d")
    ref = caglioti_2theta(U, V, W)
    got = caglioti_d(LAM, a, b, c)
    err = max(abs(got(x) - ref(x)) / ref(x)
              for x in (5.0, 0.5 * tmax, 0.75 * tmax, tmax))
    assert err < 0.45, err


def test_convert_is_exact_for_constant_width():
    """U=V=0（纯常数 W）时两基等价，换基必须精确——这是可断言的恒等情形。

    反过来说：只有当 FWHM 随角度变化时才两基不等价，而那正是要测量的区别，
    所以「往返回到原系数」不是合法断言（d 基拟不出 tan 基的高角发散）。
    """
    W = 0.035
    for tmax in (90.0, 120.0):
        a, b, c = convert_width_basis(0.0, 0.0, W, LAM, 5.0, tmax,
                                      frm="tan", to="d")
        assert a == pytest.approx(0.0, abs=1e-12)
        assert b == pytest.approx(0.0, abs=1e-12)
        assert c == pytest.approx(W, rel=1e-9)


def test_cli_flag_wires_basis():
    from xinrefinement.cli.refine import _build_inputs, build_parser

    root = Path(__file__).resolve().parent.parent
    xy = str(root / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    cif = str(root / "xinrefinement" / "data" / "anatase.cif")
    p = build_parser()
    assert _build_inputs(p.parse_args(["refine", xy, cif])).profile.width_basis == "tan"
    got = _build_inputs(p.parse_args(["refine", xy, cif,
                                      "--width-basis", "d"]))
    assert got.profile.width_basis == "d"


def test_forward_actually_uses_basis():
    """换基必须真的改变计算谱，否则是死字段。"""
    import numpy as np

    from xinrefinement.core.dtypes import Pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import compute_phase_profile

    root = Path(__file__).resolve().parent.parent
    st = parse_cif(root / "xinrefinement" / "data" / "anatase.cif")
    grid = np.arange(20.0, 60.0, 0.02)
    base = dict(zero=0.0, U=0.08, V=-0.01, W=0.02, eta=0.6, anode="Cu",
                integrated=True)
    a = compute_phase_profile(st, grid, ProfileParams(**base), 20.0, 60.0)
    b = compute_phase_profile(st, grid, ProfileParams(width_basis="d", **base),
                              20.0, 60.0)
    assert not np.allclose(a, b, rtol=0, atol=0)
    # 且必须仍是有限正值
    assert np.isfinite(a).all() and np.isfinite(b).all()
    assert (a >= 0).all() and (b >= 0).all()
    del Pattern


def test_basis_survives_solve_roundtrip():
    """精修内部会**重建** ProfileParams；若重建时丢了 width_basis，整条链会
    静默退回 tan 基（U/V/W 被当 tan 系数用），实验结论全部作废。"""
    from pathlib import Path as _P

    from xinrefinement.core.patterns import load_pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.refine.nonlinear import RefineConfig, refine

    root = _P(__file__).resolve().parent.parent
    pat = load_pattern(root / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    st = parse_cif(root / "xinrefinement" / "data" / "anatase.cif")
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False, width_basis="d")
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=3, max_iter=8, tmin=5.0, tmax=90.0)
    res = refine([st], pat, prm, cfg)
    assert res.params.width_basis == "d"


def test_basis_affects_aniso_path_too():
    """各向异性（Popa LB / TCH）路径走 split_fwhm，**也必须**尊重换基。

    这是实测漏洞：`aniso` 开着的相不经过 `width_function`，只在
    `split_fwhm` 内部用 `fwhm_gaussian`（tan 基）。若不补线，7 样全开
    `aniso` 的换基实验会两臂同值 —— 一个假的「无收益」结论。
    """
    from xinrefinement.core.profile.size_strain import fwhm_gaussian

    U, V, W = 0.08, -0.01, 0.02
    for pos in (20.0, 60.0, 110.0):
        a = fwhm_gaussian(pos, U, V, W)
        b = fwhm_gaussian(pos, U, V, W, basis="d")
        assert a != b, f"2θ={pos} 处换基没有影响"
    # 默认参数必须与历史调用逐位一致
    assert fwhm_gaussian(37.0, U, V, W) == fwhm_gaussian(
        37.0, U, V, W, basis="tan", wavelength=1.5406)


def test_aniso_on_changes_basis_result():
    """端到端：开各向异性 + 换基，计算谱必须不同。"""
    import numpy as np

    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import (
        ProfileParams, aniso_default, compute_phase_profile)

    root = Path(__file__).resolve().parent.parent
    st = parse_cif(root / "xinrefinement" / "data" / "anatase.cif")
    grid = np.arange(20.0, 80.0, 0.02)
    aniso = {st.name: aniso_default(LAM, 0.0, 0.05)}
    base = dict(zero=0.0, U=0.08, V=-0.01, W=0.02, eta=0.6, anode="Cu",
                integrated=True, aniso=aniso)
    a = compute_phase_profile(st, grid, ProfileParams(**base), 20.0, 80.0)
    b = compute_phase_profile(st, grid,
                              ProfileParams(width_basis="d", **base), 20.0, 80.0)
    assert not np.allclose(a, b, rtol=0, atol=0)
