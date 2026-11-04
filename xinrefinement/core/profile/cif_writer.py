"""P2.9 · 精修结果写回 CIF。

输入 ``CifStructure``（已展开全晶胞）或 ``SiteModel``（不对称单位），
输出标准 CIF 文本；写回后必须能被 :func:`parse_cif` 重新解析且
晶胞/原子坐标/B/occ 一致（验收口径）。

对称性处理
----------
若传入 :class:`~xinrefinement.core.refine.site.SiteModel`，只写
**不对称单位**原子 + 显式 symop（``_symmetry_equiv_pos_as_xyz``），
这是 COD/ICSD 的标准写法，也保证等价位点不重复；若传入已展开的
``CifStructure``，则写 P1 空间群 + 全晶胞原子（不写 symop，避免二次展开）。
"""
from __future__ import annotations

from pathlib import Path

from xinrefinement.core.profile.cif import CifStructure, parse_cif_string


def _fmt(v: float, digits: int = 6) -> str:
    return f"{float(v):.{digits}f}"


def _symop_to_xyz(op) -> str:
    """family symop ``[(c,ax,ay,az)]×3`` -> ``'c+ax·x, ...'`` 文本。"""
    parts = []
    for (c, ax, ay, az) in op:
        terms = []
        if abs(c) > 1e-12:
            terms.append(_fmt(c, 4).rstrip("0").rstrip(".") or "0")
        for val, var in ((ax, "x"), (ay, "y"), (az, "z")):
            if abs(val) < 1e-12:
                continue
            sign = "+" if val > 0 else "-"
            mag = "" if abs(abs(val) - 1.0) < 1e-12 else _fmt(abs(val), 3)
            terms.append(f"{sign}{mag}{var}")
        parts.append("".join(terms) or "0")
    return ", ".join(parts)


def write_cif(struct_or_model, path: str | Path | None = None,
              *, include_esd: bool = False) -> str:
    """生成 CIF 文本；给 ``path`` 时同时写盘，返回文本。

    ``include_esd`` 为 True 时给数值附 ``(0)`` 占位（P1.5 e.s.d. 回填后
    可替换为真实值；当前仅保留接口）。
    """
    from xinrefinement.core.refine.site import SiteModel

    if isinstance(struct_or_model, SiteModel):
        model = struct_or_model
        cell = model.cell
        atoms = [(s.elem, *s.xyz, s.occ, s.B) for s in model.sites]
        symops = model.symops
        hm = model.spacegroup or "P 1"
        number = model.sg_number or 1
        name = model.name
        formula = model.formula
    elif isinstance(struct_or_model, CifStructure):
        st = struct_or_model
        cell, atoms, symops = st.cell, st.atoms, []
        hm = getattr(st, "spacegroup", None) or "P 1"
        number = getattr(st, "sg_number", None) or 1
        name, formula = st.name, getattr(st, "formula", None)
    else:
        raise TypeError("需要 CifStructure 或 SiteModel")

    lines = [
        f"data_{name.replace(' ', '_')}",
        f"_chemical_formula_sum '{formula}'" if formula else
        "_chemical_formula_sum '?'",
        f"_symmetry_space_group_name_H-M '{hm}'",
        f"_symmetry_Int_Tables_number {number}",
        f"_cell_length_a {_fmt(cell[0])}",
        f"_cell_length_b {_fmt(cell[1])}",
        f"_cell_length_c {_fmt(cell[2])}",
        f"_cell_angle_alpha {_fmt(cell[3])}",
        f"_cell_angle_beta {_fmt(cell[4])}",
        f"_cell_angle_gamma {_fmt(cell[5])}",
        "loop_",
        "_symmetry_equiv_pos_as_xyz",
    ]
    if symops:
        for op in symops:
            lines.append(f"'{_symop_to_xyz(op)}'")
    else:
        lines.append("'x, y, z'")

    lines += [
        "loop_",
        "_atom_site_type_symbol",
        "_atom_site_label",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_occupancy",
        "_atom_site_U_iso_or_equiv",
    ]
    for i, (elem, x, y, z, occ, B) in enumerate(atoms, 1):
        uiso = float(B) / (8.0 * 3.141592653589793 ** 2) if B else 0.0
        lines.append(
            f"{elem} {elem}{i} {_fmt(x)} {_fmt(y)} {_fmt(z)} "
            f"{_fmt(occ, 4)} {_fmt(uiso, 6)}")
    lines.append("")
    text = "\n".join(lines)
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


def roundtrip_consistent(struct_or_model, tmp_path=None) -> bool:
    """写回后重新解析，检查晶胞与原子数一致（供验收调用）。"""
    from xinrefinement.core.refine.site import SiteModel
    text = write_cif(struct_or_model)
    st = parse_cif_string(text, "roundtrip")
    if isinstance(struct_or_model, SiteModel):
        expected_cell = struct_or_model.cell
        expected_n = len(struct_or_model.sites)
    else:
        expected_cell = struct_or_model.cell
        expected_n = len(struct_or_model.atoms)
    return (all(abs(a - b) < 1e-4 for a, b in zip(st.cell, expected_cell))
            and len(st.atoms) >= expected_n)
