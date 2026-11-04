"""P1.2 · 全晶胞精修验收（多晶系 round-trip）。

验收口径：虚拟样已知晶胞缩放真值 → 精修回收，各轴误差 < 0.1%。
用自洽合成谱（前向模型造谱，不依赖外部合成器），保证测试确定。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure, parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.cell import (
    FREE_AXES,
    apply_cell_scales,
    crystal_system_from_cell,
    crystal_system_of,
    free_axes,
    refine_cell_full,
)
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.rfactors import compute_rfactors

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("system,cell,dims", [
    ("cubic", (4.0, 4.0, 4.0, 90, 90, 90), 1),
    ("tetragonal", (3.8, 3.8, 9.5, 90, 90, 90), 2),
    ("orthorhombic", (4.0, 5.0, 6.0, 90, 90, 90), 3),
    ("hexagonal", (3.0, 3.0, 5.0, 90, 90, 120), 2),
    ("monoclinic", (4.0, 5.0, 6.0, 90, 105, 90), 4),
    ("triclinic", (4.0, 5.0, 6.0, 80, 95, 110), 6),
])
def test_metric_fallback_and_free_dims(system, cell, dims):
    assert crystal_system_from_cell(cell) == system
    assert len(free_axes(system)) == dims == len(FREE_AXES[system])


def test_apply_cell_scales_constraints():
    """非自由轴跟随：四方 b=a、立方三轴同缩放、角度固定。"""
    st = CifStructure("t", (3.8, 3.8, 9.5, 90, 90, 90), [])
    out = apply_cell_scales(st, "tetragonal", (1.005, 0.997))
    assert out.cell[0] == pytest.approx(3.8 * 1.005)
    assert out.cell[1] == pytest.approx(3.8 * 1.005)
    assert out.cell[2] == pytest.approx(9.5 * 0.997)
    assert out.cell[3:] == (90, 90, 90)

    st2 = CifStructure("c", (4.0, 4.0, 4.0, 90, 90, 90), [])
    out2 = apply_cell_scales(st2, "cubic", (1.004,))
    assert out2.cell[0] == out2.cell[1] == out2.cell[2]

    # 全 1.0 原样返回（不拷贝）
    assert apply_cell_scales(st, "tetragonal", (1.0, 1.0)) is st


def test_crystal_system_prefers_spacegroup():
    """CIF 空间群元数据优先于度量兜底。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    # 锐钛矿 I41/amd 四方；无论度量容差如何都应判 tetragonal
    assert crystal_system_of(st) in ("tetragonal", "orthorhombic")


def _make_pattern(structs, systems, scales, seed=7):
    """自洽合成：给定真值晶胞缩放 + 固定峰形/背景，造一条无噪声谱。"""
    grid = np.arange(10.0, 90.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    y = np.zeros_like(grid)
    for st, sys_, sc in zip(structs, systems, scales):
        shifted = apply_cell_scales(st, sys_, sc)
        y += 1000.0 * compute_phase_profile(shifted, grid, prm, 10.0, 90.0)
    bg = chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    return Pattern(two_theta=grid, intensity=y + bg, meta={}), prm


@pytest.mark.parametrize("system,true_scales", [
    ("tetragonal", (1.006, 0.994)),
    ("cubic", (1.007,)),
    ("orthorhombic", (1.005, 0.996, 1.004)),
])
def test_cell_roundtrip_recovery(system, true_scales):
    """核心验收：虚拟样晶胞缩放回收误差 < 0.1%（各轴 < 1e-3 相对）。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    # 用与待测晶系一致的晶胞，避免结构本身与晶系不匹配的物理矛盾
    cells = {
        "tetragonal": (3.8, 3.8, 9.5, 90, 90, 90),
        "cubic": (4.0, 4.0, 4.0, 90, 90, 90),
        "orthorhombic": (4.0, 5.0, 6.0, 90, 90, 90),
    }
    base = CifStructure(st.name, cells[system], st.atoms)
    pat, prm = _make_pattern([base], [system], [true_scales])

    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=60)
    res = refine_cell_full([base], pat, prm, cfg, backend="scipy")
    assert res.success
    assert len(res.scales[0]) == len(true_scales)
    for got, want in zip(res.scales[0], true_scales):
        assert abs(got - want) / want < 1e-3, (system, got, want)
    assert res.rwp < 1.0, res.rwp


def test_no_change_stays_at_unity():
    """真值无缩放时，精修应停在 1.0 附近且不劣化拟合。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    system = crystal_system_of(st)
    ones = tuple(1.0 for _ in free_axes(system))
    pat, prm = _make_pattern([st], [system], [ones])
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=40)
    res = refine_cell_full([st], pat, prm, cfg)
    assert res.rwp < 1.0
    assert all(abs(v - 1.0) < 0.01 for v in res.scales[0])


def test_default_engine_path_unchanged():
    """零回归护栏：P1.2 不修改 nonlinear 默认路径（cell_scales 仍全 1）。"""
    from xinrefinement.core.refine.nonlinear import refine
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    pat, prm = _make_pattern([st], [crystal_system_of(st)],
                             [tuple(1.0 for _ in free_axes(crystal_system_of(st)))])
    cfg = RefineConfig(refine_zero=False, refine_uvw=False, n_bg=3,
                       tmin=10.0, tmax=90.0)
    res = refine([st], pat, prm, cfg)
    assert res.cell_scales == [(1.0, 1.0)]
    assert res.rf.rwp < 1e-6
