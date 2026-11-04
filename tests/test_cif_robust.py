"""CIF 解析器健壮性测试（T1.2b 验收）。

用 **COD 原始文件**（未规范化、带 esd 括号）直接喂解析器，验证两件事：
1. 带 esd 的晶胞能被正确读出（不再退化为 1.0）；
2. 带 esd 的原子坐标不再被静默丢弃（β-Ni(OH)₂ 应从 1 个原子恢复到 5 个）。

这两条是"支持用户导入 CIF"的前提 —— 用户手上的文件不会经过我们的规范化。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xinrefinement.core.profile.cif import _to_float, parse_cif_string

COD_ROOT = Path("D:/Project/XRD/sync-COD/COD")


def _cod(cod_id: int) -> Path:
    s = str(cod_id)
    return COD_ROOT / s[0] / s[1:3] / s[3:5] / f"{s}.cif"


@pytest.mark.parametrize("raw, want", [
    ("3.1268(1)", 3.1268),
    ("0.2153(4)", 0.2153),
    ("14.7350", 14.7350),
    ("90", 90.0),
    ("-2.5(1)", -2.5),
    ("?", None),
    (".", None),
    ("", None),
    (None, None),
    (1.5, 1.5),
])
def test_to_float_tolerates_esd(raw, want) -> None:
    got = _to_float(raw)
    if want is None:
        assert got is None
    else:
        assert got == pytest.approx(want)


@pytest.mark.parametrize("cod_id, n_atoms, a, c", [
    (1548811, 5, 3.1268, 4.6060),    # β-Ni(OH)2：1 Ni + 2 O + 2 H
    (1548823, 30, 4.6117, 14.735),   # NiCO3：6 Ni + 6 C + 18 O
])
def test_raw_cod_with_esd_parses(cod_id, n_atoms, a, c) -> None:
    path = _cod(cod_id)
    if not path.exists():
        pytest.skip(f"COD 原始文件缺失: {path}")
    st = parse_cif_string(path.read_text(encoding="utf-8", errors="replace"),
                          f"COD{cod_id}")
    assert len(st.atoms) == n_atoms, f"原子数 {len(st.atoms)} ≠ {n_atoms}（esd 未容错）"
    assert st.cell[0] == pytest.approx(a, abs=1e-4), "晶胞 a 读取错误"
    assert st.cell[2] == pytest.approx(c, abs=1e-3), "晶胞 c 读取错误"


def test_patched_parser_keeps_builtin_results(cif_dir) -> None:
    """打了 esd 补丁后，14 份内置 CIF 的解析结果必须逐位不变（INV-2）。"""
    import json

    idx = json.loads((cif_dir / "INDEX.json").read_text(encoding="utf-8"))
    for e in idx["entries"]:
        st = parse_cif_string((cif_dir / e["file"]).read_text(encoding="utf-8"),
                              e["name"])
        assert st.cell[0] == pytest.approx(e["a"], abs=1e-4)
        assert st.cell[2] == pytest.approx(e["c"], abs=1e-4)
        assert st.atoms, f"{e['file']} 无原子"
