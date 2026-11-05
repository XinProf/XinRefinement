"""v1.3 · μ·r 计算器（Brindley 微吸收输入端自动化）。

背景：v1.2.0 给了按相 Brindley 校正 ``ProfileParams.microabs``，但 μ·r 只能
用户手填。v1.3 评审同时**证伪了「精修 μ·r」**（Brindley 因子是每相常数
标量，与线性层每相自由 scale 完全简并，单谱不可辨识且 LM 会漂移到边界）
——μ·r 的正确来源是**化学成分计算**或实测。

本模块从 CIF 自动算每相的线吸收系数 μ：

    μ/ρ(相) = Σ_i w_i · (μ/ρ)_i        w_i = 元素质量分数（按晶胞占位）
    ρ(相)   = Z·M / (N_A·V)            （与 qpa 同源的晶胞密度）
    μ       = (μ/ρ)·ρ                  [cm⁻¹] → /1e4 → [μm⁻¹]
    μ·r     = μ[μm⁻¹] · r[μm]          r = 用户给的晶粒尺寸 (μm)

(μ/ρ)_i 内嵌自 xraylib 4.3（NIST/Chantler 评估，见 ``mu_table.py``），
能量取各阳极 Kα1 波长，与 ``core.profile.shape.KA_DOUBLET`` 严格一致——
微吸收发生在衍射能量上，必须用同一波长。

质量分数按**晶胞内占位原子**计（不依赖 ``_chemical_formula_sum``）：
n_i·A_i / Σ n_j·A_j，n = 对称展开后的晶胞原子数 × 占位率。这比化学式
解析更稳（CIF 化学式常见归约/缺项），且与 ``infer_z`` 的口径一致。
"""
from __future__ import annotations

import math

from xinrefinement.core.mu_table import MU_RHO
from xinrefinement.core.profile.cif import CifStructure

#: 支持的阳极 → Kα1 波长 (Å)，与 shape.KA_DOUBLET 逐位一致
ANODE_WAVELENGTH = {
    "Cu": 1.54056, "Co": 1.78897, "Cr": 2.28970,
    "Fe": 1.93604, "Mo": 0.70930, "Ag": 0.55941,
}

#: 阿伏伽德罗常数 (mol⁻¹)
N_AVOGADRO = 6.02214076e23


def phase_mass_fractions(struct: CifStructure) -> dict[str, float]:
    """晶胞占位原子 → 元素质量分数 {symbol: w}（归一化，和为 1）。

    原子表元素名经 ``element_from_symbol`` 规范化；未知元素（表里没有
    摩尔质量或 μ 数据的）抛 ValueError —— 静默跳过会算出错误的 μ。
    """
    from xinrefinement.core.refine.qpa import ATOMIC_MASS

    counts: dict[str, float] = {}
    for (elem, _x, _y, _z, occ, _B) in struct.atoms:
        e = (elem or "").strip().capitalize()
        if not e:
            continue
        if e not in ATOMIC_MASS:
            raise ValueError(f"CIF「{struct.name}」含未知元素: {elem!r}")
        counts[e] = counts.get(e, 0.0) + float(occ)
    if not counts:
        raise ValueError(f"CIF「{struct.name}」无原子，无法算质量分数")
    total = sum(n * ATOMIC_MASS[e] for e, n in counts.items())
    if total <= 0:
        raise ValueError(f"CIF「{struct.name}」质量分数计算失败")
    return {e: n * ATOMIC_MASS[e] / total for e, n in counts.items()}


def phase_mu_rho(struct: CifStructure, anode: str = "Cu") -> float:
    """相的混合质量衰减系数 μ/ρ (cm²/g)，按晶胞元素质量分数加权。"""
    key = (anode or "").strip()
    if key not in ANODE_WAVELENGTH:
        raise ValueError(
            f"不支持阳极 {anode!r}，可选: {sorted(ANODE_WAVELENGTH)}")
    fr = phase_mass_fractions(struct)
    missing = [e for e in fr if e not in MU_RHO]
    if missing:
        raise ValueError(
            f"CIF「{struct.name}」元素 {missing} 无 μ/ρ 数据（表覆盖 Z=1–94）")
    return sum(w * MU_RHO[e][key] for e, w in fr.items())


def phase_density(struct: CifStructure, formula: str | None = None) -> float:
    """理论密度 ρ = Z·M / (N_A·V) (g/cm³)。

    Z/口径与 ``qpa.qpa_inputs_from_cif`` 完全一致（Z 按占位反算，
    不信 CIF 自述值）；formula 省略时用 CIF 自带化学式。
    """
    from xinrefinement.core.refine.qpa import qpa_inputs_from_cif

    z, vol_a3, mass = qpa_inputs_from_cif(struct, formula)
    # V[Å³] = V·1e-24 cm³；每晶胞质量 = Z·M/N_A (g)
    return (z * mass / N_AVOGADRO) / (vol_a3 * 1e-24)


def calc_mu_r(struct: CifStructure, grain_um: float,
              anode: str = "Cu",
              formula: str | None = None) -> dict:
    """计算一相的 Brindley 输入 μ·r。

    grain_um : 平均晶粒半径 r (μm)。Brindley 模型用的是**球半径**；
               用户若给直径需自行除 2（GUI 提示注明）。
    返回 {mur, mu_cm, mu_rho, density, anode}；grain_um ≤ 0 抛 ValueError。

    单位链：(μ/ρ)[cm²/g] × ρ[g/cm³] = μ[cm⁻¹] → ÷1e4 = μ[μm⁻¹]，
    μ·r = μ[μm⁻¹] × r[μm]（无量纲）。
    """
    g = float(grain_um)
    if not math.isfinite(g) or g <= 0:
        raise ValueError(f"晶粒尺寸 r 必须为正数，得到 {grain_um!r}")
    mu_rho = phase_mu_rho(struct, anode)
    rho = phase_density(struct, formula)
    mu_cm = mu_rho * rho                    # cm⁻¹
    mur = mu_cm / 1e4 * g                   # μm⁻¹ × μm
    return {
        "mur": mur,
        "mu_cm": mu_cm,
        "mu_rho": mu_rho,
        "density": rho,
        "anode": (anode or "").strip(),
    }


def calc_microabs(phases: list[CifStructure],
                  grains: dict[str, float],
                  anode: str = "Cu") -> dict[str, float]:
    """批量：{相名: 晶粒 r(μm)} → {相名: μ·r}（直接可填 ProfileParams.microabs）。

    grains 未覆盖的相跳过（用户没给 r 的相不校正，与 microabs 缺相语义一致）。
    """
    out: dict[str, float] = {}
    for st in phases:
        g = grains.get(st.name)
        if g is None:
            continue
        out[st.name] = calc_mu_r(st, g, anode)["mur"]
    return out
