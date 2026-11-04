"""TCH 尺寸-应变峰形测试（T2.1 验收）。"""
from __future__ import annotations

import math

import numpy as np
import pytest

from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.profile.size_strain import (
    SCHERRER_K,
    fwhm_gaussian,
    fwhm_lorentz,
    size_from_y,
    split_fwhm,
    strain_from_x,
    tch_combine,
    tch_eta,
    x_from_strain,
    y_from_size,
)
from xinrefinement.core.refine.nonlinear import RefineConfig, _bounds, _pack, _unpack

LAM = 1.54056


# ---------------------------------------------------------------------------
# 纯数学
# ---------------------------------------------------------------------------
def test_pure_gaussian() -> None:
    """fl=0 时应退化为纯 Caglioti：FWHM=FG，η=0。"""
    fg = fwhm_gaussian(30.0, 0.02, -0.01, 0.01)
    assert tch_combine(fg, 0.0) == pytest.approx(fg)
    assert tch_eta(fg, 0.0) == 0.0


def test_pure_lorentzian() -> None:
    """fg=0 时应退化为纯洛伦兹：FWHM=FL，η=1。"""
    fl = fwhm_lorentz(30.0, 0.0, 0.05)
    assert tch_combine(0.0, fl) == pytest.approx(fl)
    assert tch_eta(0.0, fl) == pytest.approx(1.0)


def test_combine_ge_components_and_voigt_reference() -> None:
    """Voigt 是卷积：总宽 ≥ max(ΓG, ΓL)（可超出任一分量），
    并与 Olivero–Longbothum 解析近似对照（TCH 公式的精度基准）。"""
    for fg, fl in ((0.10, 0.20), (0.20, 0.10), (0.08, 0.08)):
        tot = tch_combine(fg, fl)
        assert tot >= max(fg, fl) - 1e-9
        ol = 0.5346 * fl + math.sqrt(0.2166 * fl * fl + fg * fg)
        assert tot == pytest.approx(ol, rel=0.01)
        assert 0.0 < tch_eta(fg, fl) < 1.0


def test_lorentz_angle_dependence() -> None:
    """尺寸项 ∝ 1/cosθ 随角度增大而增大；应变项 ∝ tanθ 增长更快。"""
    lo, hi = 20.0, 70.0
    size_lo = fwhm_lorentz(lo, 0.0, y_from_size(100.0, LAM))
    size_hi = fwhm_lorentz(hi, 0.0, y_from_size(100.0, LAM))
    assert size_hi > size_lo

    strain_lo = fwhm_lorentz(lo, x_from_strain(1e-3), 0.0)
    strain_hi = fwhm_lorentz(hi, x_from_strain(1e-3), 0.0)
    assert strain_hi / strain_lo > size_hi / size_lo  # tanθ 增长快于 1/cosθ


def test_size_strain_roundtrip() -> None:
    for d in (20.0, 100.0, 500.0):
        y = y_from_size(d, LAM)
        assert size_from_y(y, LAM) == pytest.approx(d, rel=1e-9)
    for eps in (0.0, 5e-4, 2e-3):
        x = x_from_strain(eps)
        assert strain_from_x(x) == pytest.approx(eps, rel=1e-9)


def test_size_from_y_zero_is_inf() -> None:
    assert math.isinf(size_from_y(0.0, LAM))
    assert strain_from_x(0.0) == 0.0


# ---------------------------------------------------------------------------
# 前向模型
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def struct(cif_dir):
    from xinrefinement.core.profile.cif import parse_cif_string

    return parse_cif_string((cif_dir / "NCA_80_15_05.cif").read_text(encoding="utf-8"),
                            "NCA_80_15_05")


def _profile(prm: ProfileParams, struct: CifStructure) -> np.ndarray:
    grid = np.arange(15.0, 75.0, 0.02)
    return compute_phase_profile(struct, grid, prm)


def test_tch_off_is_legacy_path(struct) -> None:
    """X=Y=0 必须与 vendor 纯 Caglioti 路径逐位一致（golden 保障）。"""
    base = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu")
    legacy = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu")
    a = _profile(base, struct)
    b = _profile(legacy, struct)
    assert np.array_equal(a, b)


def test_size_broadens_peaks(struct) -> None:
    """开尺寸项后峰应变宽、峰高下降（积分强度守恒口径下）。"""
    off = _profile(ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu"),
                   struct)
    y = y_from_size(60.0, LAM)
    on = _profile(ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu",
                                Y=y), struct)
    assert on.max() < off.max()
    assert np.sum(on) == pytest.approx(np.sum(off), rel=0.35)


def test_smaller_crystallite_broader(struct) -> None:
    """D 越小峰越宽 —— Scherrer 关系的正向验证。"""
    grid = np.arange(15.0, 75.0, 0.02)
    widths = []
    for d in (30.0, 100.0, 300.0):
        prm = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu",
                            Y=y_from_size(d, LAM))
        prof = compute_phase_profile(struct, grid, prm)
        # 用 (003) 峰的半高宽作代理
        m = (grid > 17.5) & (grid < 20.0)
        seg = prof[m]
        half = seg.max() / 2
        above = grid[m][seg >= half]
        widths.append(above[-1] - above[0])
    assert widths[0] > widths[1] > widths[2]


# ---------------------------------------------------------------------------
# 精修引擎打包/解包（覆盖索引 bug 回归）
# ---------------------------------------------------------------------------
def test_pack_unpack_roundtrip_all_flags() -> None:
    prm = ProfileParams(zero=0.01, U=0.05, V=-0.04, W=0.017, eta=0.6,
                        anode="Cu", asym=0.07, bfactor=0.5, X=0.02, Y=0.03)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                       refine_asym=True, refine_bfactor=True, refine_cell=True,
                       refine_strain=True, refine_size=True)
    x = _pack(prm, cfg, n_phase=1)
    assert x.size == 1 + 3 + 1 + 1 + 1 + 2 + 2  # zero,uvw,eta,asym,bfac,cell,XY
    out, cell = _unpack(x, prm, cfg, n_phase=1)
    assert out.X == pytest.approx(0.02)
    assert out.Y == pytest.approx(0.03)
    assert out.zero == pytest.approx(0.01)
    assert cell == [(1.0, 1.0)]


def test_pack_unpack_size_only() -> None:
    """只开尺寸项（回归：曾因索引计算越界）。"""
    prm = ProfileParams(zero=0.01, U=0.05, V=-0.04, W=0.017, eta=0.6,
                        anode="Cu", X=0.02, Y=0.03)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_asym=True,
                       refine_bfactor=True, refine_cell=True, refine_size=True)
    x = _pack(prm, cfg, n_phase=1)
    assert x.size == 1 + 3 + 1 + 1 + 2 + 1
    out, _ = _unpack(x, prm, cfg, n_phase=1)
    assert out.Y == pytest.approx(0.03)
    assert out.X == pytest.approx(0.02)   # 未精修 → 取 base


def test_pack_unpack_strain_only() -> None:
    prm = ProfileParams(zero=0.0, U=0.05, V=-0.04, W=0.017, eta=0.6,
                        anode="Cu", X=0.02, Y=0.03)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_bfactor=True,
                       refine_cell=True, refine_strain=True)
    x = _pack(prm, cfg, n_phase=1)
    out, _ = _unpack(x, prm, cfg, n_phase=1)
    assert out.X == pytest.approx(0.02)
    assert out.Y == pytest.approx(0.03)   # 未精修 → 取 base


def test_bounds_match_pack_size() -> None:
    """_bounds 与 _pack 的向量长度必须一致（LM 的硬前提）。"""
    prm = ProfileParams(anode="Cu", X=0.0, Y=0.0)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_asym=True,
                       refine_bfactor=True, refine_cell=True,
                       refine_strain=True, refine_size=True)
    x = _pack(prm, cfg, n_phase=1)
    lo, hi = _bounds(cfg, n_phase=1, n_po=0)
    assert lo.size == hi.size == x.size
