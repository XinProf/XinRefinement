"""P1.3/P1.4 · 原子坐标 / B / 占位精修验收。

验收：站点模型还原 CIF（原子数、峰位数、Wyckoff 自由维度）+
虚拟样 round-trip（坐标 <1e-3、B ±0.2 Å²、occ ±0.02）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.profile.struct import compute_peaks
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.site import (
    B_BOUNDS,
    OCC_BOUNDS,
    XYZ_BOUNDS,
    parse_site_model,
    refine_sites,
)

ROOT = Path(__file__).resolve().parent.parent
ANATASE = ROOT / "xinrefinement" / "data" / "anatase.cif"
RUTILE = ROOT / "xinrefinement" / "data" / "rutile.cif"


@pytest.mark.parametrize("path,n_atoms", [(ANATASE, 12), (RUTILE, 6)])
def test_site_model_reproduces_parse_cif(path, n_atoms):
    """零参数向量重建的结构必须与 parse_cif 展开结果等价。"""
    model = parse_site_model(path)
    st0 = parse_cif(path)
    st = model.to_structure(np.zeros(model.n_params))
    assert len(st.atoms) == len(st0.atoms) == n_atoms
    p1, _ = compute_peaks(st, 1.5406, 10.0, 90.0)
    p2, _ = compute_peaks(st0, 1.5406, 10.0, 90.0)
    assert len(p1) == len(p2)
    assert np.allclose([p[0] for p in p1], [p[0] for p in p2], atol=1e-8)


def test_wyckoff_free_dims():
    """特殊位坐标固定（n_free=0），一般位 3 维自由。"""
    m = parse_site_model(ANATASE)
    assert m.sites[0].elem == "Ti" and m.sites[0].n_free == 0
    assert m.sites[1].elem == "O" and m.sites[1].n_free == 1
    # 恒等操作（P1）的一般位应 3 维
    from xinrefinement.core.symops import symops_from_spg, free_coordinate_dims
    p1 = symops_from_spg(number=1)
    assert free_coordinate_dims(p1, (0.123, 0.456, 0.789)) == 3


def _make_pattern(model, truth_x, seed=11):
    """自洽合成：用真值参数造无噪声谱（固定峰形/背景）。"""
    grid = np.arange(10.0, 90.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    st = model.to_structure(np.asarray(truth_x, dtype=float))
    y = 1000.0 * compute_phase_profile(st, grid, prm, 10.0, 90.0)
    bg = chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    return Pattern(two_theta=grid, intensity=y + bg, meta={}), prm


def _truth_vector(model, *, dz=0.0, dB=0.0, d_occ=0.0) -> np.ndarray:
    """构造真值向量：每个位点 [自由坐标系数…, dB, d_occ]。"""
    out = []
    for s in model.sites:
        out.extend([0.0] * s.n_free)
        out.append(dB)
        out.append(d_occ)
    out = np.asarray(out, dtype=float)
    # O 位的自由坐标（第 2 个位点）注入 dz
    if dz and len(model.sites) > 1:
        off = model.offsets[1]
        out[off] = dz
    return out


def test_xyz_roundtrip():
    """P1.3 核心：原子坐标回收误差 < 1e-3。"""
    m = parse_site_model(ANATASE)
    truth = _truth_vector(m, dz=0.012)
    pat, prm = _make_pattern(m, truth)
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=80)
    res = refine_sites([m], pat, prm, cfg, backend="scipy",
                       free_kinds=("xyz",))
    assert res.success
    off = m.offsets[1]
    assert abs(res.params[off] - 0.012) < 1e-3, res.params
    assert res.rwp < 1.0
    # 未启用的 B/occ 保持 0
    assert abs(res.params[off + 1]) < 1e-9


def test_B_roundtrip():
    """P1.4：各向同性 B 回收 ±0.2 Å²。"""
    m = parse_site_model(ANATASE)
    truth = _truth_vector(m, dB=0.8)
    pat, prm = _make_pattern(m, truth)
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=80)
    res = refine_sites([m], pat, prm, cfg, backend="scipy",
                       free_kinds=("B",))
    assert res.success
    offs = [o + s.n_free for o, s in zip(m.offsets, m.sites)]
    assert all(abs(res.params[o] - 0.8) < 0.2 for o in offs), res.params


def test_occ_roundtrip():
    """P1.4：占位率回收 ±0.02（相对变化）。

    **物理约束**：单相里若所有位点 occ 同时缩放，等价于整体强度缩放，
    会被变量投影的线性层 scale 完全吸收（数学上不可辨识）。故真值只扰动
    O 位点、Ti 固定，让结构因子**形状**改变而非整体幅度。
    """
    m = parse_site_model(ANATASE)
    truth = _truth_vector(m)
    # 只改 O 位点（第 2 个位点）的 occ
    off_o = m.offsets[1] + m.sites[1].n_free + 1
    truth[off_o] = 0.12
    pat, prm = _make_pattern(m, truth)
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=80)
    res = refine_sites([m], pat, prm, cfg, backend="scipy",
                       free_kinds=("occ",))
    assert res.success
    assert abs(res.params[off_o] - 0.12) < 0.02, res.params


def test_symmetry_equivalence_preserved():
    """精修后等价原子仍联动：原子总数与峰位数不膨胀。"""
    m = parse_site_model(RUTILE)
    st0 = m.to_structure(np.zeros(m.n_params))
    truth = _truth_vector(m, dz=0.01, dB=0.4)
    st1 = m.to_structure(truth)
    assert len(st1.atoms) == len(st0.atoms)
    p0, _ = compute_peaks(st0, 1.5406, 10.0, 90.0)
    p1, _ = compute_peaks(st1, 1.5406, 10.0, 90.0)
    assert len(p1) == len(p0)


def test_bounds_are_frozen():
    """边界冻结值（防止后续误改破坏 golden）。"""
    assert XYZ_BOUNDS == (-0.05, 0.05)
    assert B_BOUNDS == (-2.0, 2.0)
    assert OCC_BOUNDS == (-0.30, 0.30)


def test_zero_vector_is_identity():
    """全零向量重建结构 = 原始 CIF（逐位，含原子坐标）。"""
    m = parse_site_model(ANATASE)
    st = m.to_structure(np.zeros(m.n_params))
    st0 = parse_cif(ANATASE)
    for a, b in zip(st.atoms, st0.atoms):
        assert a[0] == b[0]
        assert np.allclose(a[1:4], b[1:4], atol=1e-12)
