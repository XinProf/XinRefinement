"""v1.5 M8c：多型建议（只建议、不自动改用户 CIF）。

实测依据：样 7 的方石英被给成高温 β（Fd-3m），样品实为低温 α（P4₁2₁2），
端到端 14.689 → 14.031%（−0.66 pt）且 ΔB_iso 撞界消失。但 7 样复测里
有 4 个样都出现「某相 ΔB_iso 撞界」，绝大多数是织构/标度吸收——所以触发
必须**三条同时满足**：撞界 + 化学式相同 + 空间群等于该候选的基线多型。

这里用**构造**的相做测试（内置数据只有 α 方石英），把 spacegroup 字段
改成 Fd-3m 来模拟用户误给的高温相，避免把用户目录的 CIF 引进仓库。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.refine import polymorph as P
from xinrefinement.core.refine.nonlinear import BISO_BOUNDS

DATA = P.DATA_DIR


@pytest.fixture(scope="module")
def alpha():
    st = parse_cif(DATA / "cristobalite_alpha.cif")
    st.name = "5 Entry_96-900-8234"
    return st


@pytest.fixture(scope="module")
def beta():
    """模拟用户误给的 β 方石英：同一化学式，空间群换成 Fd-3m。

    ``CifStructure`` 不是 dataclass（不能 ``dataclasses.replace``），
    故重新解析一份再改字段，避免污染 module 级的 alpha fixture。
    """
    st = parse_cif(DATA / "cristobalite_alpha.cif")
    st.name = "5 Entry_96-900-8234"
    st.spacegroup = "F d -3 m"
    return st


def _res(phase, b):
    return SimpleNamespace(params=SimpleNamespace(b_iso={phase.name: b}))


def test_formula_key_normalizes_order_and_spaces():
    assert P.formula_key("O2 Si") == "O2Si"
    assert P.formula_key("SiO2") == "O2Si"
    assert P.formula_key("Si O2") == "O2Si"
    assert P.formula_key(None) == ""
    assert P.formula_key("") == ""


def test_spacegroup_key_is_insensitive_to_spacing():
    assert P.spacegroup_key("F d -3 m") == "fd-3m"
    assert P.spacegroup_key("P 41 21 2") == "p41212"
    assert P.spacegroup_key(None) == ""


def test_builtin_cif_matches_cod_9017338(alpha):
    assert alpha.spacegroup == "P 41 21 2"
    assert [round(v, 4) for v in alpha.cell[:3]] == [4.9727, 4.9727, 6.9257]
    assert len(alpha.atoms) == 12          # 4 Si + 8 O（Z=4）


def test_suggests_when_hit_and_polymorph_match(beta):
    sug = P.suggest(_res(beta, BISO_BOUNDS[1]), [beta])
    assert len(sug) == 1
    assert sug[0].phase_name == beta.name
    assert sug[0].candidate.key == "cristobalite_alpha"
    assert "ΔB_iso" in sug[0].reason


def test_no_suggestion_below_bound(beta):
    assert P.suggest(_res(beta, BISO_BOUNDS[1] - 0.5), [beta]) == []


def test_no_suggestion_when_spacegroup_already_alpha(alpha):
    """已经是 α 就不该再报（否则会给出一个原地打转的按钮）。"""
    assert P.suggest(_res(alpha, BISO_BOUNDS[1]), [alpha]) == []


def test_no_suggestion_for_other_composition():
    st = parse_cif(DATA / "anatase.cif")
    st.name = "t"
    st.spacegroup = "F d -3 m"                  # 空间群对上但化学式 O2Ti
    assert P.suggest(_res(st, BISO_BOUNDS[1]), [st]) == []


def test_apply_keeps_phase_name_and_swaps_structure(alpha, beta):
    sug = P.suggest(_res(beta, BISO_BOUNDS[1]), [beta])[0]
    out = P.apply_suggestion([beta], sug)
    assert len(out) == 1
    assert out[0].name == beta.name                    # 相名保持不变
    assert out[0].spacegroup == "P 41 21 2"
    assert len(out[0].atoms) == 12
    # 入参不被修改（返回新列表）
    assert beta.spacegroup == "F d -3 m"


def test_apply_raises_for_unknown_phase(alpha):
    sug = P.Suggestion(phase_name="不存在", candidate=P.CANDIDATES[0],
                       reason="x")
    with pytest.raises(KeyError):
        P.apply_suggestion([alpha], sug)


def test_builtin_cif_lookup():
    assert P.builtin_cif("cristobalite_alpha").exists()
    with pytest.raises(KeyError):
        P.builtin_cif("nope")
