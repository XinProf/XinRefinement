# vendored from PolyXRD-RutAna :: rutana/core/refine/qpa.py
"""QPA 定量换算（Hill–Howard，vendor 副本 · T5.3）。

Hill–Howard (Rietveld) 质量分数:

    W_p = S_p·Z_p·V_p·M_p / Σ_q S_q·Z_q·V_q·M_q

其中 S 为精修相标度、Z 为晶胞内化学式单元数、V 为晶胞体积 (Å³)、
M 为化学式量。推导：衍射强度 ∝ 晶胞数 × |F|²，晶胞数 ∝ w_p/(Z·M·V)，
故 w_p ∝ S·Z·M·V。

**权威依据**（本卡实施时联网核实，非凭记忆）：
- Hill & Howard, J. Appl. Cryst. 20 (1987) 467（ neutron QPA 原始文献）；
- IUCr Erice 2011 教程（QPA 标准）：`W_α = S_α(ZMV)_α / Σ_k S_k(ZMV)_k`，
  Z = 晶胞内化学式单元数，M = 化学式量，V = 晶胞体积。

**★酸检（RutAna 原样继承）**：以 TiO₂ 锐钛型(Z=4) / 金红石型(Z=2) 为例，
(ZMV)_锐/(ZMV)_金 = (4×136.3)/(2×62.42) ≈ 4.368；若两者 S 相同，
w_锐 = 4×136.3/(4×136.3 + 2×62.42) ≈ 81.37%（不是 50%）。
任何 scale→质量分数的换算错误都会被测试立刻打出来。

NCA 侧改动：
- import 路径改为 `xinrefinement.core.profile.cif`；
- 保留 `to_ratio` 供双相对比使用（NCA 侧主要用于主相 vs 杂质相）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from xinrefinement.core.profile.cif import CifStructure

# 常用元素摩尔质量 (g/mol, IUPAC 2021)。TiO2 = 47.867 + 2×15.999 = 79.865 ≈ 79.87
ATOMIC_MASS = {
    "H": 1.008, "He": 4.003, "Li": 6.94, "Be": 9.012, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Na": 22.990,
    "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "K": 39.098, "Ca": 40.078, "Ti": 47.867, "V": 50.942,
    "Cr": 51.996, "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693,
    "Cu": 63.546, "Zn": 65.38, "Ga": 69.723, "Ge": 72.630, "As": 74.922,
    "Se": 78.971, "Br": 79.904, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Ag": 107.868, "Cd": 112.414, "Sn": 118.710,
    "Sb": 121.760, "Ba": 137.327, "La": 138.905, "Ce": 140.116, "W": 183.84,
    "Pt": 195.084, "Au": 196.967, "Hg": 200.592, "Pb": 207.2, "Bi": 208.980,
}

_MASS_RE = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)")

#: 非金属（含类金属）元素集 —— 化学式显示时排在金属之后
_NONMETALS = {"H", "He", "B", "C", "N", "O", "F", "Ne", "Si", "P", "S", "Cl",
              "As", "Se", "Br", "Te", "I", "At"}

#: 金属显示优先级：**正极材料惯例** Li → Ni → Co → Al（NCM 为 Li → Ni → Co → Mn）
#: 文献惯例写 LiNi0.8Co0.15Al0.05O2 / LiNi0.8Co0.1Mn0.1O2，本序保证
#: `format_formula` 输出与文献写法一致。
_METAL_PRIORITY = ("Li", "Na", "K", "Rb", "Cs", "Ni", "Co", "Mn", "Fe", "Cr",
                   "V", "Ti", "Al", "Ca", "Mg", "Zn", "Cu", "Sr", "Ba", "Sn",
                   "Pb", "Ag", "Au", "Pt", "Pd", "W", "Mo")

#: 阴离子显示优先级
_ANION_PRIORITY = ("C", "H", "O", "N", "S", "F", "Cl", "P", "Se", "Br", "I")


@dataclass(frozen=True)
class PhaseWeight:
    """单相 QPA 输入/输出。"""

    name: str
    scale: float
    Z: int
    volume: float
    mass: float
    weight: float


def formula_mass(formula: str) -> float:
    """化学式 -> 摩尔质量 (g/mol)。支持 'TiO2' / 'O2 Ti' (COD 风格) 等。"""
    total = 0.0
    for elem, cnt in _MASS_RE.findall(formula.replace(" ", "")):
        if elem not in ATOMIC_MASS:
            raise ValueError(f"未知元素摩尔质量: {elem} (in {formula})")
        total += ATOMIC_MASS[elem] * (float(cnt) if cnt else 1.0)
    if total <= 0.0:
        raise ValueError(f"化学式量解析失败: {formula}")
    return total


def _formula_counts(formula: str) -> dict[str, float]:
    """化学式 -> {元素: 个数}。"""
    counts: dict[str, float] = {}
    for elem, cnt in _MASS_RE.findall(formula.replace(" ", "")):
        counts[elem] = counts.get(elem, 0.0) + (float(cnt) if cnt else 1.0)
    return counts


def infer_z(struct: CifStructure, formula: str | None = None) -> int:
    """由 CIF 全晶胞原子数 + 化学式反算 Z（晶胞内化学式单元数）。

    对每个元素计算 n_cell/n_formula，取一致的最小整数值。
    锐钛型 I41/amd 应得 4，金红石型 P42/mnm 应得 2（见 test_qpa）。

    **NCA 修改（T5.3）**：
    - `formula` 省略时自动取 CIF 自带的 `_chemical_formula_sum` —— 定量**不应**
      让用户手填化学式（内置 NCA_80_15_05 实为 `Li1.03Ni0.77Co0.1Mn0.1O2`，与教科书
      配方 `LiNi0.8Co0.1Mn0.1O2` 不同，手填会直接算错摩尔质量）。
    - **不信 CIF 自述的 `_cell_formula_units_Z`**：内置若干 CIF 是手工改占位
      生成的，继承模板的 Z 与实际不符（前驱体 CO3 自述 6、OH 自述 1）。
      这里的 Z 一律由「原子数 ÷ 配方」反算，自述值仅供 `z_consistency` 交叉校验。
    """
    f = formula or getattr(struct, "formula", None)
    if not f:
        raise ValueError(
            f"CIF「{struct.name}」缺少 _chemical_formula_sum 且未给定化学式，"
            f"无法反算 Z（请手动指定该相的化学式）")
    f_counts = _formula_counts(f)
    if not f_counts:
        raise ValueError(f"化学式解析失败: {f}")
    cell_counts: dict[str, float] = {}
    for (elem, _x, _y, _z, occ, _B) in struct.atoms:
        cell_counts[elem] = cell_counts.get(elem, 0.0) + float(occ)
    estimates = []
    for elem, n_f in f_counts.items():
        if elem in cell_counts and n_f > 0:
            estimates.append((elem, cell_counts[elem] / n_f))
    if not estimates:
        raise ValueError(f"CIF 原子与化学式 {f} 无公共元素")
    z_est = min(v for _e, v in estimates)
    z_int = int(round(z_est))
    if z_int < 1:
        raise ValueError(f"Z 反算得到非正整数: {z_est} (formula={f})")
    # 所有元素都要落在同一个 Z 上（容差 0.05 绝对值，吸收 1/3→0.333 的截断）
    bad = [(e, v) for e, v in estimates if abs(v - z_int) > 0.05]
    if bad:
        raise ValueError(
            f"Z 反算不一致: 公式 {f} 给出 {z_int}，但元素 "
            + ", ".join(f"{e}={v:.3f}" for e, v in bad)
            + " 偏离（检查化学式与 CIF 占位是否匹配）")
    return z_int


def z_consistency(struct: CifStructure, z: int) -> dict:
    """Z 的一致性检查（反算值 vs CIF 自述值）。

    内置若干 CIF 的 `_cell_formula_units_Z` 是模板继承值，与实际占位不符，
    故只作**提示**，不作为计算依据。
    """
    declared = getattr(struct, "z_declared", None)
    return {
        "z_computed": int(z),
        "z_declared": declared,
        "consistent": True if declared is None else (int(declared) == int(z)),
        "note": None if declared is None or int(declared) == int(z)
        else f"CIF 自述 Z={declared}，与按原子占位反算的 Z={z} 不符（以反算值为准）",
    }


def format_formula(formula: str) -> str:
    """化学式规范化显示（去空格、按正极材料惯例排序、小数用 `g` 格式）。

    COD 风格 'Co0.1 Li1.03 Mn0.1 Ni0.77 O2' -> 'Li1.03Ni0.77Co0.1Mn0.1O2'

    **排序规则**：金属在前（Li → Ni → Co → Mn → Fe → …，即 NCA 命名本身的
    元素序），阴离子在后（C → H → O → …）。不按原子序排 —— 原子序会把 O
    排到 Mn/Ni/Co 前面（O=8 < Mn=25），得到 'Li1.03O2Mn0.1Co0.1Ni0.77'，
    与文献写法 'LiNi0.8Co0.1Mn0.1O2' 不符，界面和报告上都别扭。
    """
    counts = _formula_counts(formula)
    if not counts:
        return formula

    def _sort_key(elem: str) -> tuple[int, int, str]:
        is_metal = elem not in _NONMETALS
        if is_metal:
            pri = _METAL_PRIORITY
        else:
            pri = _ANION_PRIORITY
        idx = pri.index(elem) if elem in pri else len(pri)
        return (0 if is_metal else 1, idx, elem)

    out = []
    for elem, n in sorted(counts.items(), key=lambda kv: _sort_key(kv[0])):
        out.append(elem if abs(n - 1.0) < 1e-9 else f"{elem}{n:g}")
    return "".join(out)


def qpa_inputs_from_cif(struct: CifStructure,
                        formula: str | None = None) -> tuple[int, float, float]:
    """从 CifStructure 提取 (Z, V(Å³), M(g/mol)) 三元组，供 qpa_weights。

    `formula` 省略时用 CIF 自带配方。Z 一律由原子占位反算（见 `infer_z`）。
    """
    f = formula or getattr(struct, "formula", None)
    if not f:
        raise ValueError(
            f"CIF「{struct.name}」缺少 _chemical_formula_sum，无法定量"
            f"（请手动指定该相的化学式）")
    z = infer_z(struct, f)
    return z, float(struct.volume), formula_mass(f)


def qpa_weights(weights: list[tuple[str, float, int, float, float]]) -> list[PhaseWeight]:
    """tuple = (name, scale, Z, cell_volume, formula_mass) -> 归一化质量分数。

    weight_p = S_p·Z_p·V_p·M_p / Σ；scale 全零或非法时抛 ValueError。
    """
    if not weights:
        raise ValueError("至少需要一个物相")
    total = 0.0
    raw = []
    for (name, scale, z, vol, mass) in weights:
        if scale < 0 or z <= 0 or vol <= 0 or mass <= 0:
            raise ValueError(f"非法 QPA 输入: {(name, scale, z, vol, mass)}")
        s = float(scale) * float(z) * float(vol) * float(mass)
        raw.append(s)
        total += s
    if total <= 0.0:
        raise ValueError("所有相 scale 之积为 0，无法定量")
    return [PhaseWeight(name=w[0], scale=float(w[1]), Z=int(w[2]),
                        volume=float(w[3]), mass=float(w[4]),
                        weight=float(s / total))
            for w, s in zip(weights, raw)]


def to_ratio(ws: list[PhaseWeight], i_main: int, i_other: int) -> tuple[float, float]:
    """从 PhaseWeight 列表取 (w_main %, w_other %)，两相相对比率。"""
    wm = ws[i_main].weight
    wo = ws[i_other].weight
    tot = wm + wo
    if tot <= 0.0:
        raise ValueError("两相质量分数之和为 0")
    return (100.0 * wm / tot, 100.0 * wo / tot)
