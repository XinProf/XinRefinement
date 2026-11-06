"""v1.3 · μ·r 计算器（core.absorption）验收。

契约：
- 内嵌 μ/ρ 表（xraylib 生成）对已知元素/能量与文献值一致（±5%）；
- 相密度 ρ=Z·M/(N_A·V) 与文献一致（锐钛矿 3.89 / 金红石 4.24）；
- μ·r = (μ/ρ)·ρ·r / 1e4，对 r 线性；
- 批量接口跳过未给晶粒尺寸的相（与 microabs 缺相语义一致）；
- 非法输入（未知阳极 / r≤0 / 未知元素）显式报错，不静默；
- CLI --grain-size 解析与优先级（手工 --microabs 覆盖自动值）。
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from xinrefinement.core.absorption import (  # noqa: E402
    ANODE_WAVELENGTH,
    calc_mu_r,
    calc_microabs,
    phase_density,
    phase_mass_fractions,
    phase_mu_rho,
)
from xinrefinement.core.mu_table import MU_RHO  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "xinrefinement" / "data"


@pytest.fixture(scope="module")
def anatase():
    return parse_cif(DATA / "anatase.cif")


@pytest.fixture(scope="module")
def rutile():
    return parse_cif(DATA / "rutile.cif")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_mu_table_literature_values():
    """抽查元素 μ/ρ (cm²/g, Cu Kα 8.048 keV) 与文献/NIST 值一致（±5%）。

    参考：International Tables Vol C / NIST XCOM 量级对照——
    Fe≈304、Ti≈202、O≈11.5、Pb≈232（L 边以下）、Pb@Mo Kα 小得多。
    """
    ref = {"Fe": 304.0, "Ti": 202.0, "O": 11.5, "Pb": 232.0}
    for sym, expect in ref.items():
        got = MU_RHO[sym]["Cu"]
        assert got == pytest.approx(expect, rel=0.05), sym
    # Mo Kα（17.48 keV）能量更高，Pb 的 μ/ρ 显著低于 Cu Kα
    assert MU_RHO["Pb"]["Mo"] < MU_RHO["Pb"]["Cu"]


def test_mu_table_structure():
    """表覆盖 Z=1–94 常见符号 × 6 阳极，数值为正且随能量单调下降（远离边）。"""
    assert len(MU_RHO) >= 92
    for sym in ("H", "C", "O", "Fe", "Pb", "U"):
        row = MU_RHO[sym]
        assert set(row) == set(ANODE_WAVELENGTH)
        assert all(v > 0 for v in row.values())
    # 同元素、跨阳极能量差 3 倍以上时（Cu→Ag），μ/ρ 应下降（无吸收边跨越）
    for sym in ("O", "Si", "Fe", "Pb"):
        assert MU_RHO[sym]["Ag"] < MU_RHO[sym]["Cu"], sym


def test_anatase_density_and_mu_rho(anatase):
    """锐钛矿 TiO2：ρ=3.89 g/cm³（文献），μ/ρ≈124 cm²/g（文献 124–129）。"""
    rho = phase_density(anatase)
    assert rho == pytest.approx(3.89, rel=0.01)
    murho = phase_mu_rho(anatase, "Cu")
    assert murho == pytest.approx(126.0, rel=0.05)


def test_rutile_density(rutile):
    assert phase_density(rutile) == pytest.approx(4.24, rel=0.01)


def test_calc_mu_r_linear_in_grain_and_units(anatase):
    """μ·r 对 r 线性；单位链 (μ/ρ)[cm²/g]·ρ[g/cm³]/1e4·r[μm]。"""
    a = calc_mu_r(anatase, 2.0)
    b = calc_mu_r(anatase, 4.0)
    assert b["mur"] == pytest.approx(2.0 * a["mur"], rel=1e-12)
    # 单位链复核：mur ≈ mu_rho × rho × r / 1e4
    expect = a["mu_rho"] * a["density"] * 2.0 / 1e4
    assert a["mur"] == pytest.approx(expect, rel=1e-9)
    assert a["mu_cm"] == pytest.approx(a["mu_rho"] * a["density"], rel=1e-9)


def test_mass_fractions_normalization(anatase):
    fr = phase_mass_fractions(anatase)
    assert set(fr) == {"Ti", "O"}
    assert sum(fr.values()) == pytest.approx(1.0)
    # TiO2 质量分数：Ti ≈ 47.867/79.865 ≈ 0.5995
    assert fr["Ti"] == pytest.approx(0.5995, abs=0.005)


def test_calc_microabs_skips_unnamed(anatase, rutile):
    grains = {anatase.name: 2.0}          # 只给锐钛矿
    out = calc_microabs([anatase, rutile], grains)
    assert set(out) == {anatase.name}
    assert out[anatase.name] == pytest.approx(calc_mu_r(anatase, 2.0)["mur"])


def test_invalid_inputs(anatase):
    with pytest.raises(ValueError, match="阳极"):
        calc_mu_r(anatase, 2.0, anode="Ag2")
    with pytest.raises(ValueError, match="晶粒"):
        calc_mu_r(anatase, 0.0)
    with pytest.raises(ValueError, match="晶粒"):
        calc_mu_r(anatase, -1.0)


def test_unknown_element_raises():
    # 手工构造含表外元素的相（parse_cif 会丢弃无法识别的元素符号，
    # 故不能用替换法构造）
    from xinrefinement.core.profile.cif import CifStructure

    bad = CifStructure("bad", (3.78, 3.78, 9.51, 90.0, 90.0, 90.0),
                       [("Zz", 0.0, 0.0, 0.0, 1.0, 1.0),
                        ("O", 0.0, 0.0, 0.35, 1.0, 1.0)])
    with pytest.raises(ValueError, match="未知元素"):
        phase_mass_fractions(bad)


def test_gui_dialog_smoke(qapp, anatase, rutile):
    """PhaseEditDialog 带自动计算控件可实例化，settings 语义不变。"""
    from xinrefinement.gui.dialogs import PhaseEditDialog

    dlg = PhaseEditDialog([anatase, rutile], None, anode="Cu")
    assert dlg._anode == "Cu"
    got = dlg.settings()
    for st in (anatase, rutile):
        assert st.name in got
        assert got[st.name]["microabs"] is None    # 默认未启用


def test_density_fallback_on_inconsistent_formula(anatase):
    """v1.4 #20：化学式与占位不一致时按晶胞占位质量回退，不抛错。

    构造：把锐钛矿的 ``formula`` 改成与占位不符的 TiO3，``infer_z`` 必失败；
    回退密度仍应等于按正常公式算出的物理密度（晶胞原子没变）。
    """
    good = calc_mu_r(anatase, 2.0)
    assert good["density_source"] == "formula_z"
    assert good["warning"] is None
    saved = anatase.formula
    try:
        anatase.formula = "TiO3"
        got = calc_mu_r(anatase, 2.0)
    finally:
        anatase.formula = saved
    assert got["density_source"] == "cell_mass"
    assert got["warning"] and "化学式" in got["warning"]
    assert got["density"] == pytest.approx(good["density"], rel=1e-12)
    assert got["mur"] == pytest.approx(good["mur"], rel=1e-12)
