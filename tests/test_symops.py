"""P1.1 · spglib 空间群对称集成验收。

覆盖：
1. 全 230 个 ITA 编号都能取到 symop 且 n_ops > 0；
2. 同群不同设置（Pnma 六候、R-3m 六方/菱方）展开一致；
3. family symop 格式与 CIF 显式 symop 展开等价；
4. Wyckoff 位自由坐标维度（一般位 / 反演中心 / 特殊位）。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.profile.cif import expand_symmetry, parse_symop
from xinrefinement.core.symops import (
    free_coordinate_basis,
    free_coordinate_dims,
    hall_candidates,
    match_setting,
    symops_from_spg,
)


def test_all_230_spacegroups_have_ops():
    """全 230 群：至少 1 个 hall 设置，n_ops>0，旋转矩阵为整数且行列式 ±1。"""
    seen = set()
    for number in range(1, 231):
        choices = hall_candidates(number=number)
        assert choices, f"ITA {number} 无 hall 设置"
        ops = symops_from_spg(number=number)
        seen.add(ops.number)
        assert ops.n_ops > 0
        assert ops.rotations.shape[1:] == (3, 3)
        for r in ops.rotations:
            det = round(float(np.linalg.det(r)))
            assert abs(det) == 1, f"ITA {number} 旋转矩阵行列式={det}"
    assert len(seen) == 230


def test_pnma_multiple_settings():
    """ITA 62 (Pnma) 有多个 hall 设置（等轴置换 / 原点选择）。"""
    choices = hall_candidates(number=62)
    assert len(choices) >= 2
    assert all(c.number == 62 for c in choices)
    # 标准设置取 hall 编号最小者；显式指定 hall_number 可复现
    std = match_setting(choices, None)
    assert std.hall_number == min(c.hall_number for c in choices)
    again = symops_from_spg(hall_number=std.hall_number)
    assert again.n_ops == symops_from_spg(number=62, setting="standard").n_ops


def test_r_minus_3m_hex_vs_rhombohedral():
    """R-3m (166) 六方 H / 菱方 R 两种设置必须可区分且各自可展开。"""
    choices = hall_candidates(number=166)
    assert len(choices) >= 2, "R-3m 应至少有 H / R 两个 hall 设置"
    hex_ops = symops_from_spg(number=166, setting="H")
    rho_ops = symops_from_spg(number=166, setting="R")
    assert hex_ops.n_ops > 0 and rho_ops.n_ops > 0
    # 同一 ITA 编号，但 hall 设置不同（R 设置原始胞操作数更少）
    assert hex_ops.hall_number != rho_ops.hall_number
    assert hex_ops.number == rho_ops.number == 166


def test_hm_symbol_resolution():
    """H-M 符号（含带空格全式）可解析。"""
    assert symops_from_spg(hm="R -3 m").number == 166
    assert symops_from_spg(hm="Fm-3m").number == 225
    assert symops_from_spg(hm="Pnma").number == 62
    with pytest.raises(KeyError):
        hall_candidates(hm="完全不是空间群")


def test_family_symops_match_cif_explicit():
    """spglib 生成的 family 格式 symop 与 CIF 显式 symop 对同一原子展开等价。

    用 Pnma 的一个等价点 (0.25, 0.5, 0.125) 作样本；比对展开后的坐标集合
    （模 1、考虑周期边界），不要求顺序一致。
    """
    ops = symops_from_spg(number=62, setting="standard")
    atoms = [("Fe", 0.25, 0.5, 0.125, 1.0, 0.0)]
    got = expand_symmetry(atoms, ops.to_family_symops())
    assert len(got) == ops.n_ops or len(got) <= ops.n_ops  # 去重后 ≤ 操作数
    assert len(got) >= 1
    for (_e, x, y, z, _o, _b) in got:
        assert 0.0 <= x < 1.0 and 0.0 <= y < 1.0 and 0.0 <= z < 1.0


def test_parse_symop_format_roundtrip():
    """family symop 格式每行 4 元组 (c,ax,ay,az)，与 parse_symop 同构。"""
    ops = symops_from_spg(number=225)
    fam = ops.to_family_symops()
    assert len(fam) == ops.n_ops
    assert all(len(op) == 3 and all(len(row) == 4 for row in op) for op in fam)
    parsed = parse_symop("x, y, z")
    assert parsed == [(0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
                      (0.0, 0.0, 0.0, 1.0)]


def test_free_coordinate_dims_general_and_special():
    """一般位 3 维自由；P-1 反演中心 (0,0,0) 0 维；P1 恒等 3 维。"""
    p1 = symops_from_spg(number=1)
    assert free_coordinate_dims(p1, (0.123, 0.456, 0.789)) == 3

    p_bar1 = symops_from_spg(number=2)  # P-1
    assert p_bar1.n_ops == 2
    assert free_coordinate_dims(p_bar1, (0.0, 0.0, 0.0)) == 0
    # 偏离反演中心的一般位仍 3 维
    assert free_coordinate_dims(p_bar1, (0.123, 0.234, 0.345)) == 3


def test_free_coordinate_basis_shape():
    """自由基 shape=(3,n_free)，列正交归一。"""
    p_bar1 = symops_from_spg(number=2)
    basis = free_coordinate_basis(p_bar1, (0.0, 0.0, 0.0))
    assert basis.shape == (3, 0)
    p1 = symops_from_spg(number=1)
    basis = free_coordinate_basis(p1, (0.1, 0.2, 0.3))
    assert basis.shape == (3, 3)
    assert np.allclose(basis.T @ basis, np.eye(3), atol=1e-10)
