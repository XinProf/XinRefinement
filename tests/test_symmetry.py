"""空间群元数据测试（T4.2 验收）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from xinrefinement.core.symmetry import (
    _POINT_GROUP_TABLE,
    describe,
    lookup,
    lookup_by_number,
    normalize_hm,
)

CIF_DIR = Path(__file__).resolve().parents[1] / "xinrefinement" / "data" / "cif"


def test_acceptance_r_minus_3m() -> None:
    """任务卡验收口径：R -3 m -> 三方 / -3m / -3m / hR。"""
    info = lookup("R -3 m")
    assert info.crystal_system_zh == "三方"
    assert info.point_group == "-3m"
    assert info.laue_group == "-3m"
    assert info.bravais == "hR"
    assert info.number == 166


@pytest.mark.parametrize("sym", ["R -3 m", "R-3m", "R -3 m :H", "r-3m", "R  -3  m"])
def test_normalization_variants(sym: str) -> None:
    assert lookup(sym).hm == "R-3m"


def test_normalize_hm_strips_setting() -> None:
    assert normalize_hm("R -3 m :H") == "R-3m"
    assert normalize_hm("P 21/c") == "P21/c"


def test_p_minus_3m1() -> None:
    info = lookup("P -3 m 1")
    assert info.number == 164
    assert info.crystal_system_zh == "三方"
    assert info.bravais == "hP"


def test_r_minus_3c() -> None:
    info = lookup("R -3 c")
    assert info.number == 167
    assert info.point_group == "-3m"
    assert info.bravais == "hR"


def test_cubic_and_orthorhombic() -> None:
    assert lookup("Fd-3m").crystal_system_zh == "立方"
    assert lookup("Fd-3m").bravais == "cF"
    assert lookup("Pnma").crystal_system_zh == "正交"
    assert lookup("Pnma").point_group == "mmm"
    assert lookup("Pnma").bravais == "oP"


def test_lookup_by_number() -> None:
    assert lookup_by_number(166).hm == "R-3m"
    assert lookup_by_number(227).hm == "Fd-3m"
    with pytest.raises(KeyError):
        lookup_by_number(999)


def test_unknown_symbol_raises() -> None:
    with pytest.raises(KeyError):
        lookup("完全不是空间群")


def test_derived_fallback() -> None:
    """未登记符号走规则兜底（derived=True），点群/劳厄群仍正确。

    用 `P 42/m`（#84）作样本：它不在 `spacegroups.json` 的收录范围内，
    但 H-M 符号可直接推出点群 4/m → 四方晶系 / 劳厄群 4/mmm。
    （早前用的是 `P 21/n`，NCA 版已把它作为单斜设定正式登记 —— 三水铝石
    Al(OH)₃ 要用，见 `test_full_form_alias_resolves`。）
    """
    info = lookup("P 42/m")
    assert info.derived is True
    assert info.point_group == "4/m"
    assert info.laue_group == "4/mmm"
    assert info.crystal_system == "tetragonal"


def test_full_form_alias_resolves() -> None:
    """单斜**全式** H-M 符号须归一到短式并命中登记项（NCA 版新增）。

    COD 原始件普遍写全式：三水铝石是 `P 1 21/n 1`、残碱是 `C 1 2/c 1`。
    不归一化会走规则兜底推出 `1/m` 这种不存在于 32 点群表的点群，
    最终抛 KeyError —— 结果卡的晶系/点群/空间群/劳厄群会全空。
    """
    gib = lookup("P 1 21/n 1")
    assert gib.hm == "P21/n"
    assert gib.number == 14
    assert gib.crystal_system == "monoclinic"
    assert gib.point_group == "2/m"

    lico3 = lookup("C 1 2/c 1")
    assert lico3.hm == "C2/c"
    assert lico3.number == 15
    assert lico3.bravais == "mC"


def test_tetragonal_lialo2_resolves() -> None:
    """γ-LiAlO₂ 的 P4₁2₁2（#92）必须能查到 —— NCA 铝偏析相要用。"""
    info = lookup("P 41 21 2")
    assert info.hm == "P41212"
    assert info.number == 92
    assert info.crystal_system == "tetragonal"
    assert info.point_group == "422"
    assert info.laue_group == "4/mmm"


def test_point_group_table_consistency() -> None:
    """32 点群表：每个点群的劳厄类必须与其晶系相符。"""
    laue_by_system = {}
    for pg, (system, laue) in _POINT_GROUP_TABLE.items():
        laue_by_system.setdefault(system, set()).add(laue)
    assert len(_POINT_GROUP_TABLE) == 32
    for system, laues in laue_by_system.items():
        assert len(laues) == 1, f"{system} 对应多个劳厄类: {laues}"


def test_all_builtin_cifs_resolve() -> None:
    """内置 CIF 的空间群必须都能查到元数据。"""
    from xinrefinement.core.profile.cif import parse_cif

    files = sorted(CIF_DIR.glob("*.cif"))
    assert files, "内置 CIF 目录为空"
    for f in files:
        st = parse_cif(f)
        assert st.spacegroup, f"{f.name} 未解析出空间群"
        info = lookup(st.spacegroup)
        assert info.crystal_system_zh
        assert info.point_group and info.laue_group and info.bravais


def test_describe_contains_zh() -> None:
    txt = describe("R -3 m")
    assert "三方" in txt and "-3m" in txt and "hR" in txt
