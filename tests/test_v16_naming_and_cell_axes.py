"""v1.6 · 物相显示名（naming）与晶胞自由轴覆盖（axes_override）。

两件事都是「GUI 需求倒逼 core 能力」，但都必须可独立验证：

1. **显示名**：界面上不再暴露 CIF 文件名。化学式规整只做紧凑化与
   金属/非金属/阴离子再分组，**不得改变元素计数**；
2. **自由轴覆盖**：晶胞弹窗的勾选必须真正决定精修哪几个分量，
   而不像 v1.5 那样是装饰性复选框（引擎当时根本不读它）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure, parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.profile.naming import (
    DEFAULT_PHASE_LABEL_MODE,
    PHASE_LABEL_MODES,
    label_map,
    normalize_formula,
    phase_label,
    phase_labels,
)
from xinrefinement.core.refine.cell import (
    apply_cell_scales,
    free_axes,
    refine_cell_full,
    resolve_axes,
)
from xinrefinement.core.refine.linear import chebyshev_basis
from xinrefinement.core.refine.nonlinear import RefineConfig

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- naming -- #
@pytest.mark.parametrize("raw,want", [
    ("O2 Si", "SiO2"),
    ("O2 Ti0.992", "Ti0.992O2"),
    ("O4 S Zn", "ZnSO4"),
    ("Ca F2", "CaF2"),
    ("H2 O", "H2O"),
    ("Ca C O3", "CaCO3"),
    ("O3 Al2", "Al2O3"),
    ("F2 Mg", "MgF2"),
])
def test_normalize_formula_conventional_order(raw, want):
    """COD 的字母序写法（O2 Si / O4 S Zn）要变成惯用写法。"""
    assert normalize_formula(raw) == want


def test_normalize_formula_keeps_counts():
    """再分组不得改变任何元素计数（占位配方尤其要保住 0.1 这类小数）。"""
    got = normalize_formula("Co0.1 Li1.03 Ni0.77 Co0.1 Mn0.1 O2")
    assert got == "Co0.2Li1.03Ni0.77Mn0.1O2"
    # 同一元素重复出现要累加，不能丢
    assert normalize_formula("Fe1 O1 Fe1 O2") == "Fe2O3"


def test_normalize_formula_never_guesses():
    """认不出的写法只做紧凑化，不臆测结构。"""
    assert normalize_formula("(C2 H4)n") == "(C2H4)n"
    assert normalize_formula(None) is None
    assert normalize_formula("") is None


def test_phase_label_three_modes():
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    assert phase_label(st, "formula") == "TiO2"
    assert phase_label(st, "label") == "Anatase"
    assert phase_label(st, "file") == st.name
    assert DEFAULT_PHASE_LABEL_MODE == "formula"
    assert PHASE_LABEL_MODES == ("formula", "label", "file")


def test_phase_label_falls_back():
    """化学式/名称缺失时逐级回落，保证界面上永远不会是空白。"""
    bare = CifStructure("bare_phase", (4.0, 4.0, 4.0, 90, 90, 90), [])
    assert phase_label(bare, "formula") == "bare_phase"
    assert phase_label(bare, "label") == "bare_phase"

    only_formula = CifStructure("f1", (4.0, 4.0, 4.0, 90, 90, 90), [])
    only_formula.formula = "O2 Si"
    assert phase_label(only_formula, "label") == "SiO2"


def test_parse_cif_reads_mineral_name():
    """v1.6：parse_cif 要读出 _chemical_name_mineral。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    assert st.name_mineral == "Anatase"
    rutile = parse_cif(ROOT / "xinrefinement" / "data" / "rutile.cif")
    assert rutile.name_mineral == "Rutile"


def test_label_map_and_batch():
    a = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    r = parse_cif(ROOT / "xinrefinement" / "data" / "rutile.cif")
    assert phase_labels([a, r]) == ["TiO2", "Ti0.992O2"]
    m = label_map([a, r], "label")
    assert m[a.name] == "Anatase" and m[r.name] == "Rutile"


# ------------------------------------------------------------ cell axes -- #
def test_resolve_axes_matches_crystal_system():
    assert resolve_axes("cubic", None) == ("a",)
    assert resolve_axes("tetragonal", None) == ("a", "c")
    assert resolve_axes("triclinic", None) == ("a", "b", "c",
                                               "alpha", "beta", "gamma")


def test_resolve_axes_drops_illegal_and_honours_order():
    """非法轴要丢（立方给 b、四方给 beta），顺序跟随晶系定义而非用户输入。"""
    assert resolve_axes("cubic", ("a", "b", "c")) == ("a",)
    assert resolve_axes("tetragonal", ("c", "a")) == ("a", "c")
    assert resolve_axes("tetragonal", ("beta",)) == ()
    assert resolve_axes("orthorhombic", ()) == ()


def test_apply_cell_scales_subset_leaves_others_alone():
    """只勾 c 时 a/b 必须原样不动（正交晶系最干净）。"""
    st = CifStructure("o", (4.0, 5.0, 6.0, 90, 90, 90), [])
    out = apply_cell_scales(st, "orthorhombic", (1.004,), axes=("c",))
    assert out.cell[0] == pytest.approx(4.0)
    assert out.cell[1] == pytest.approx(5.0)
    assert out.cell[2] == pytest.approx(6.0 * 1.004)


def _synth(structs, systems, scales):
    grid = np.arange(10.0, 90.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    y = np.zeros_like(grid)
    for st, sys_, sc in zip(structs, systems, scales):
        y += 1000.0 * compute_phase_profile(
            apply_cell_scales(st, sys_, sc), grid, prm, 10.0, 90.0)
    bg = chebyshev_basis(grid, 3) @ np.array([300.0, 20.0, 5.0])
    return Pattern(two_theta=grid, intensity=y + bg, meta={}), prm


def test_axes_override_controls_parameter_dimension():
    """勾选决定参数向量维度，并回填到结果里供界面说明。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    base = CifStructure(st.name, (3.8, 3.8, 9.5, 90, 90, 90), st.atoms)
    pat, prm = _synth([base], ["tetragonal"], [(1.006, 0.994)])
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=60)

    full = refine_cell_full([base], pat, prm, cfg, backend="scipy")
    assert full.axes[0] == ("a", "c") and len(full.scales[0]) == 2

    only_a = refine_cell_full([base], pat, prm, cfg, backend="scipy",
                              axes_override={base.name: ("a",)})
    assert only_a.axes[0] == ("a",) and len(only_a.scales[0]) == 1
    # c 没参与精修 → 必须停在原始值
    assert only_a.cells[0][2] == pytest.approx(9.5)

    skipped = refine_cell_full([base], pat, prm, cfg, backend="scipy",
                               axes_override={base.name: ()})
    assert skipped.axes[0] == () and skipped.scales[0] == ()
    assert skipped.cells[0] == base.cell


def test_axes_override_none_is_bitwise_unchanged():
    """零回归：不给 axes_override 时与历史路径逐位一致。"""
    st = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    base = CifStructure(st.name, (3.8, 3.8, 9.5, 90, 90, 90), st.atoms)
    pat, prm = _synth([base], ["tetragonal"], [(1.006, 0.994)])
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=60)

    a = refine_cell_full([base], pat, prm, cfg, backend="scipy")
    b = refine_cell_full([base], pat, prm, cfg, backend="scipy",
                         axes_override=None)
    assert a.rwp == b.rwp
    assert a.scales == b.scales
    assert a.cells == b.cells
    assert a.axes == b.axes == (("a", "c"),)


def test_axes_override_multi_phase_is_per_phase():
    """多相各自勾不同轴：互不干扰。"""
    a = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    r = parse_cif(ROOT / "xinrefinement" / "data" / "rutile.cif")
    p1 = CifStructure(a.name, (3.8, 3.8, 9.5, 90, 90, 90), a.atoms)
    p2 = CifStructure(r.name, (4.6, 4.6, 2.96, 90, 90, 90), r.atoms)
    pat, prm = _synth([p1, p2], ["tetragonal", "tetragonal"],
                      [(1.004, 0.998), (1.002, 1.0)])
    cfg = RefineConfig(tmin=10.0, tmax=90.0, n_bg=3, max_iter=40)
    res = refine_cell_full(
        [p1, p2], pat, prm, cfg, backend="scipy",
        axes_override={p1.name: ("c",), p2.name: ("a",)})
    assert res.axes == (("c",), ("a",))
    assert len(res.scales[0]) == 1 and len(res.scales[1]) == 1
    # p1 只修 c → a 不变；p2 只修 a → c 不变
    assert res.cells[0][0] == pytest.approx(3.8)
    assert res.cells[1][2] == pytest.approx(2.96)


def test_free_axes_still_full_set():
    """历史接口不变（GUI/配方都还在用）。"""
    assert free_axes("triclinic") == ("a", "b", "c", "alpha", "beta", "gamma")
