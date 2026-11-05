# vendored from PolyXRD-RutAna :: rutana/core/profile/cif.py
"""vendor: CIF 解析与原子散射因子（T3.2）。

Vendored from PolyXRD-SynthPattern xrd_synth_engine.py + scattering_data.py —
© 2026 PolyXRD Team, dual-licensed (Academic/Commercial)，家族内复用。
复制范围: element_from_symbol / _to_float / _split_cif_line / parse_symop /
expand_symmetry / CifStructure / parse_cif / ATOMIC_SCATTERING / ATOMIC_Z /
parse_cif_string。散射因子表逐项照抄，未改动任何数值。
"""
from __future__ import annotations

import math
import re
import shlex
from pathlib import Path

# 原子X射线散射因子系数 (Cromer-Mann 4-Gaussian, 源自 pymatgen atomic_scattering_params.json)
# f(s)=Z - 41.78214*s^2 * sum_i a_i*exp(-b_i*s^2),  s=sin(theta)/lambda
ATOMIC_SCATTERING = {
    "Ac": [[6.278, 28.323], [5.195, 4.949], [2.321, 0.557], [0, 0]],
    "Ag": [[2.036, 61.497], [3.272, 11.824], [2.511, 2.846], [0.837, 0.327]],
    "Al": [[2.276, 72.322], [2.428, 19.773], [0.858, 3.08], [0.317, 0.408]],
    "Am": [[6.378, 29.156], [5.495, 5.102], [2.495, 0.565], [0, 0]],
    "Ar": [[1.274, 26.682], [2.19, 8.813], [0.793, 2.219], [0.326, 0.307]],
    "As": [[2.399, 45.718], [2.79, 12.817], [1.529, 2.28], [0.594, 0.328]],
    "At": [[6.133, 28.047], [5.031, 4.957], [2.239, 0.558], [0, 0]],
    "Au": [[2.388, 42.866], [4.226, 9.743], [2.689, 2.264], [1.255, 0.307]],
    "B": [[0.945, 46.444], [1.312, 14.178], [0.419, 3.223], [0.116, 0.377]],
    "Ba": [[7.821, 117.657], [6.004, 18.778], [3.28, 3.263], [1.103, 0.376]],
    "Be": [[1.25, 60.804], [1.334, 18.591], [0.36, 3.653], [0.106, 0.416]],
    "Bi": [[3.841, 50.261], [4.679, 11.999], [3.192, 2.56], [1.363, 0.318]],
    "Bk": [[6.502, 28.375], [5.478, 4.975], [2.51, 0.561], [0, 0]],
    "Br": [[2.166, 33.899], [2.904, 10.497], [1.395, 2.041], [0.589, 0.307]],
    "C": [[0.731, 36.995], [1.195, 11.297], [0.456, 2.814], [0.125, 0.346]],
    "Ca": [[4.47, 99.523], [2.971, 22.696], [1.97, 4.195], [0.482, 0.417]],
    "Cd": [[2.574, 55.675], [3.259, 11.838], [2.547, 2.784], [0.838, 0.322]],
    "Ce": [[5.007, 28.283], [3.98, 5.183], [1.678, 0.589], [0, 0]],
    "Cf": [[6.548, 28.461], [5.526, 4.965], [2.52, 0.557], [0, 0]],
    "Cl": [[1.452, 30.935], [2.292, 9.98], [0.787, 2.234], [0.322, 0.323]],
    "Cm": [[6.46, 28.396], [5.469, 4.97], [2.471, 0.554], [0, 0]],
    "Co": [[2.367, 61.431], [2.236, 14.18], [1.724, 2.725], [0.515, 0.344]],
    "Cr": [[2.307, 78.405], [2.334, 15.785], [1.823, 3.157], [0.49, 0.364]],
    "Cs": [[6.062, 155.837], [5.986, 19.695], [3.303, 3.335], [1.096, 0.379]],
    "Cu": [[1.579, 62.94], [1.82, 12.453], [1.658, 2.504], [0.532, 0.333]],
    "D": [[0.202, 30.868], [0.244, 8.544], [0.082, 1.273], [0, 0]],
    "Dy": [[5.332, 28.888], [4.37, 5.198], [1.863, 0.581], [0, 0]],
    "Er": [[5.436, 28.655], [4.437, 5.117], [1.891, 0.577], [0, 0]],
    "Eu": [[6.267, 100.298], [4.844, 16.066], [3.202, 2.98], [1.2, 0.367]],
    "F": [[0.387, 20.239], [0.811, 6.609], [0.475, 1.931], [0.146, 0.279]],
    "Fe": [[2.544, 64.424], [2.343, 14.88], [1.759, 2.854], [0.506, 0.35]],
    "Fr": [[6.201, 28.2], [5.121, 4.954], [2.275, 0.556], [0, 0]],
    "Ga": [[2.321, 65.602], [2.486, 15.458], [1.688, 2.581], [0.599, 0.351]],
    "Gd": [[5.225, 29.158], [4.314, 5.259], [1.827, 0.586], [0, 0]],
    "Ge": [[2.447, 55.893], [2.702, 14.393], [1.616, 2.446], [0.601, 0.342]],
    "H": [[0.202, 30.868], [0.244, 8.544], [0.082, 1.273], [0, 0]],
    "He": [[0.091, 18.183], [0.181, 6.212], [0.11, 1.803], [0.036, 0.284]],
    "Hf": [[5.588, 29.001], [4.619, 5.164], [1.997, 0.579], [0, 0]],
    "Hg": [[2.682, 42.822], [4.241, 9.856], [2.755, 2.295], [1.27, 0.307]],
    "Ho": [[5.376, 28.773], [4.403, 5.174], [1.884, 0.582], [0, 0]],
    "I": [[3.473, 39.441], [4.06, 11.816], [2.522, 2.415], [0.84, 0.298]],
    "In": [[3.153, 66.649], [3.557, 14.449], [2.818, 2.976], [0.884, 0.335]],
    "Ir": [[5.754, 29.159], [4.851, 5.152], [2.096, 0.57], [0, 0]],
    "K": [[3.951, 137.075], [2.545, 22.402], [1.98, 4.532], [0.482, 0.434]],
    "Kr": [[2.034, 29.999], [2.927, 9.598], [1.342, 1.952], [0.589, 0.299]],
    "La": [[4.94, 28.716], [3.968, 5.245], [1.663, 0.594], [0, 0]],
    "Li": [[1.611, 107.638], [1.246, 30.48], [0.326, 4.533], [0.099, 0.495]],
    "Lu": [[5.553, 28.907], [4.58, 5.16], [1.969, 0.577], [0, 0]],
    "Mg": [[2.268, 73.67], [1.803, 20.175], [0.839, 3.013], [0.289, 0.405]],
    "Mn": [[2.747, 67.786], [2.456, 15.674], [1.792, 3.0], [0.498, 0.357]],
    "Mo": [[3.12, 72.464], [3.906, 14.642], [2.361, 3.237], [0.85, 0.366]],
    "N": [[0.572, 28.847], [1.043, 9.054], [0.465, 2.421], [0.131, 0.317]],
    "Na": [[2.241, 108.004], [1.333, 24.505], [0.907, 3.391], [0.286, 0.435]],
    "Nb": [[4.237, 27.415], [3.105, 5.074], [1.234, 0.593], [0, 0]],
    "Nd": [[5.151, 28.304], [4.075, 5.073], [1.683, 0.571], [0, 0]],
    "Ne": [[0.303, 17.64], [0.72, 5.86], [0.475, 1.762], [0.153, 0.266]],
    "Ni": [[2.21, 58.727], [2.134, 13.553], [1.689, 2.609], [0.524, 0.339]],
    "Np": [[6.323, 29.142], [5.414, 5.096], [2.453, 0.568], [0, 0]],
    "O": [[0.455, 23.78], [0.917, 7.622], [0.472, 2.144], [0.138, 0.296]],
    "Os": [[5.75, 28.933], [4.773, 5.139], [2.079, 0.573], [0, 0]],
    "P": [[1.888, 44.876], [2.469, 13.538], [0.805, 2.642], [0.32, 0.361]],
    "Pa": [[6.306, 28.688], [5.303, 5.026], [2.386, 0.561], [0, 0]],
    "Pb": [[3.51, 52.914], [4.552, 11.884], [3.154, 2.571], [1.359, 0.321]],
    "Pd": [[4.436, 28.67], [3.454, 5.269], [1.383, 0.595], [0, 0]],
    "Pm": [[5.201, 28.079], [4.094, 5.081], [1.719, 0.576], [0, 0]],
    "Po": [[6.07, 28.075], [4.997, 4.999], [2.232, 0.563], [0, 0]],
    "Pr": [[5.085, 28.588], [4.043, 5.143], [1.684, 0.581], [0, 0]],
    "Pt": [[5.803, 29.016], [4.87, 5.15], [2.127, 0.572], [0, 0]],
    "Pu": [[6.415, 28.836], [5.419, 5.022], [2.449, 0.561], [0, 0]],
    "Ra": [[6.215, 28.382], [5.17, 5.002], [2.316, 0.562], [0, 0]],
    "Rb": [[4.776, 140.782], [3.859, 18.991], [2.234, 3.701], [0.868, 0.419]],
    "Re": [[5.695, 28.968], [4.74, 5.156], [2.064, 0.575], [0, 0]],
    "Rh": [[4.431, 27.911], [3.343, 5.153], [1.345, 0.592], [0, 0]],
    "Rn": [[4.078, 38.406], [4.978, 11.02], [3.096, 2.355], [1.326, 0.299]],
    "Ru": [[4.358, 27.881], [3.298, 5.179], [1.323, 0.594], [0, 0]],
    "S": [[1.659, 36.65], [2.386, 11.488], [0.79, 2.469], [0.321, 0.34]],
    "Sb": [[3.564, 50.487], [3.844, 13.316], [2.687, 2.691], [0.864, 0.316]],
    "Sc": [[3.966, 88.96], [2.917, 20.606], [1.925, 3.856], [0.48, 0.399]],
    "Se": [[2.298, 38.83], [2.854, 11.536], [1.456, 2.146], [0.59, 0.316]],
    "Si": [[2.129, 57.775], [2.533, 16.476], [0.835, 2.88], [0.322, 0.386]],
    "Sm": [[5.255, 28.016], [4.113, 5.037], [1.743, 0.577], [0, 0]],
    "Sn": [[3.45, 59.104], [3.735, 14.179], [2.118, 2.855], [0.877, 0.327]],
    "Sr": [[5.848, 104.972], [4.003, 19.367], [2.342, 3.737], [0.88, 0.414]],
    "Ta": [[5.659, 28.807], [4.63, 5.114], [2.014, 0.578], [0, 0]],
    "Tb": [[5.272, 29.046], [4.347, 5.226], [1.844, 0.585], [0, 0]],
    "Tc": [[4.318, 28.246], [3.27, 5.148], [1.287, 0.59], [0, 0]],
    "Te": [[4.785, 27.999], [3.688, 5.083], [1.5, 0.581], [0, 0]],
    "Th": [[6.264, 28.651], [5.263, 5.03], [2.367, 0.563], [0, 0]],
    "Ti": [[3.565, 81.982], [2.818, 19.049], [1.893, 3.59], [0.483, 0.386]],
    "Tl": [[5.932, 29.086], [4.972, 5.126], [2.195, 0.572], [0, 0]],
    "Tm": [[5.441, 29.149], [4.51, 5.264], [1.956, 0.59], [0, 0]],
    "U": [[6.767, 85.951], [6.729, 15.642], [4.014, 2.936], [1.561, 0.335]],
    "V": [[3.245, 76.379], [2.698, 17.726], [1.86, 3.363], [0.486, 0.374]],
    "W": [[5.709, 28.782], [4.677, 5.084], [2.019, 0.572], [0, 0]],
    "Xe": [[3.366, 35.509], [4.147, 11.117], [2.443, 2.294], [0.829, 0.289]],
    "Y": [[4.129, 27.548], [3.012, 5.088], [1.179, 0.591], [0, 0]],
    "Yb": [[5.529, 28.927], [4.533, 5.144], [1.945, 0.578], [0, 0]],
    "Zn": [[1.942, 54.162], [1.95, 12.518], [1.619, 2.416], [0.543, 0.33]],
    "Zr": [[4.105, 28.492], [3.144, 5.277], [1.229, 0.601], [0, 0]],
}

# 原子序数 (f 公式中的 Z)
ATOMIC_Z = {
    "Ac": 89, "Ag": 47, "Al": 13, "Am": 95, "Ar": 18, "As": 33, "At": 85,
    "Au": 79, "B": 5, "Ba": 56, "Be": 4, "Bi": 83, "Bk": 97, "Br": 35,
    "C": 6, "Ca": 20, "Cd": 48, "Ce": 58, "Cf": 98, "Cl": 17, "Cm": 96,
    "Co": 27, "Cr": 24, "Cs": 55, "Cu": 29, "Dy": 66, "Er": 68, "Eu": 63,
    "F": 9, "Fe": 26, "Fr": 87, "Ga": 31, "Gd": 64, "Ge": 32, "H": 1,
    "He": 2, "Hf": 72, "Hg": 80, "Ho": 67, "I": 53, "In": 49, "Ir": 77,
    "K": 19, "Kr": 36, "La": 57, "Li": 3, "Lu": 71, "Mg": 12, "Mn": 25,
    "Mo": 42, "N": 7, "Na": 11, "Nb": 41, "Nd": 60, "Ne": 10, "Ni": 28,
    "Np": 93, "O": 8, "Os": 76, "P": 15, "Pa": 91, "Pb": 82, "Pd": 46,
    "Pm": 61, "Po": 84, "Pr": 59, "Pt": 78, "Pu": 94, "Ra": 88, "Rb": 37,
    "Re": 75, "Rh": 45, "Rn": 86, "Ru": 44, "S": 16, "Sb": 51, "Sc": 21,
    "Se": 34, "Si": 14, "Sm": 62, "Sn": 50, "Sr": 38, "Ta": 73, "Tb": 65,
    "Tc": 43, "Te": 52, "Th": 90, "Ti": 22, "Tl": 81, "Tm": 69, "U": 92,
    "V": 23, "W": 74, "Xe": 54, "Y": 39, "Yb": 70, "Zn": 30, "Zr": 40,
}

_SYMBOL_RE = re.compile(r"([A-Z][a-z]?)")
_KNOWN = set(ATOMIC_SCATTERING.keys())


def element_from_symbol(raw: str | None) -> str | None:
    """从 _atom_site_type_symbol 或 label 中解析元素符号。"""
    if raw is None:
        return None
    s = raw.strip()
    # 先尝试前两个字符 (Cl, Ca, Zn, Zr ...)
    for cand in (s[:2], s[:1]):
        if cand.capitalize() in _KNOWN:
            return cand.capitalize()
    # 退化: 在字符串里找已知符号
    for m in _SYMBOL_RE.finditer(s):
        if m.group(1) in _KNOWN:
            return m.group(1)
    return None


class CifStructure:
    """一个物相: 晶胞参数 + 展开后的全晶胞原子列表。"""

    def __init__(self, name, cell, atoms):
        self.name = name
        self.cell = cell  # (a,b,c,al,be,ga)
        self.atoms = atoms  # list[(element, x,y,z, occ, B)]
        # 对称性追踪 (parse_cif 填充): 不对称单位原子数 / 对称操作数
        self.n_asym = len(atoms)
        self.n_sym_ops = 0
        # NCA 修改（T4.2）：空间群信息（H-M 符号与国际表号），解析失败为 None
        self.spacegroup = None
        self.sg_number = None
        # NCA 修改（T5.3）：化学式与自述 Z —— 定量（QPA）必须用 CIF 自带配方，
        # 不能让用户手填（内置 NCA_80_15_05 实为锂富集型 Li1.03Ni0.77Co0.1Mn0.1O2，
        # 与教科书配方 LiNi0.8Co0.1Mn0.1O2 不同，手填会直接算错摩尔质量）。
        self.formula = None       # _chemical_formula_sum 原样（COD 风格，带空格）
        self.z_declared = None    # _cell_formula_units_Z（CIF 自述值，仅作交叉校验）

    @property
    def volume(self) -> float:
        a, b, c, al, be, ga = [math.radians(x) if i >= 3 else x for i, x in enumerate(self.cell)]
        return a * b * c * math.sqrt(max(0.0,
            1 - math.cos(al) ** 2 - math.cos(be) ** 2 - math.cos(ga) ** 2
            + 2 * math.cos(al) * math.cos(be) * math.cos(ga)))


def _to_float(v):
    """宽容的 float 转换, 失败返回 None。

    # NCA 修改（T1.2b）：容忍 CIF 的标准 esd 括号写法与缺失值标记。

    原实现直接 `float(v)`，遇到 `3.1268(1)` / `0.2153(4)` 会返回 None，后果是
    **静默出错**：晶胞退化成 1.0、带 esd 的原子被整行丢弃（实测 β-Ni(OH)2
    从 5 个原子掉到 1 个，|F|² 全错且不报错）。COD 中大量条目带 esd，
    用户导入的 CIF 更是如此，故必须在解析层容忍。

    处理规则：
    - `3.1268(1)` -> 3.1268（括号内是末位不确定度，不参与数值）
    - `?` / `.` / 空 -> None（CIF 的"未知/不适用"标记）
    - 兼容 `1.234(5)e-2` 这类少见写法（先剥离括号再转）
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().strip("'\"")
    if not s or s in ("?", ".", "-"):
        return None
    if "(" in s:
        head, _, tail = s.partition("(")
        rest = tail.split(")", 1)[1] if ")" in tail else ""
        s = head + rest
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _split_cif_line(s: str) -> list[str]:
    """按空白切分 CIF 数据行, 引号内的内容 ('x, y, z') 视为一个 token。"""
    if "'" in s or '"' in s:
        try:
            return shlex.split(s)
        except ValueError:
            return s.split()
    return s.split()


# ----------------------------------------------------------------------
# 晶体学对称展开
#
# 必须做这一步: 多数 CIF (尤其 COD) 只给**不对称单位** + 对称操作。若不展开,
# 会算出大量禁戒反射。对称展开后再按距离去重, 因此"已经给满晶胞"的 CIF
# 也不会被重复计数。
# ----------------------------------------------------------------------
_SYM_TAGS = ("_symmetry_equiv_pos_as_xyz", "_space_group_symop_operation_xyz",
             "_symmetry_equiv_pos_as_xyz_", "_space_group_symop_xyz")


def parse_symop(expr: str) -> list[tuple[float, float, float, float]]:
    """'1/2-y, 1/2+x, 1/2+z' -> [(c, ax, ay, az)] (共 3 项)。

    值 = c + ax·x + ay·y + az·z  (分数坐标)。"""
    out = []
    _idx = {"x": 0, "y": 1, "z": 2}
    for part in expr.split(",")[:3]:
        s = part.replace(" ", "").replace("'", "").replace('"', "")
        c = 0.0
        coef = [0.0, 0.0, 0.0]
        for m in re.finditer(r"([+-]?)(?:(\d+)/(\d+))?([xyzXYZ])?", s):
            sign, num, den, var = m.groups()
            if not (sign or num or var):
                continue
            sgn = -1.0 if sign == "-" else 1.0
            if num and den:
                c += sgn * (int(num) / int(den))
            elif var:
                coef[_idx[var.lower()]] += sgn
        out.append((c, coef[0], coef[1], coef[2]))
    return out


#: 对称展开去重容差（分数坐标）。**不要改回 1e-4**。
#:
#: 实测依据（2026-11-05，实样 ShiJiKong1–7）：CIF 里的特殊位置普遍被四舍五入
#: 到 3 位小数，如石英 P3121 的 Si(0.530, 0, 0.333) 真值为 z=1/3。3₁ 螺旋
#: 轴生成的等价点落在 0.333 / 0.33367 / 0.99967 三处，与 0.33333… 相差
#: 3.3e-4 —— 用 1e-4 去重会**全部留下**，Si 由 3 个变 6 个（散射能力翻倍），
#: 石英相对强度与 QPA 全错，且 QPA 因 Z 反算不一致而整体跳过。
#: 3 位小数的四舍五入误差上限 ≈ 5e-4，取 2e-3 留 4 倍余量；a≈5 Å 时
#: 2e-3 仅 0.01 Å，远小于任何真实原子间距（最短化学键 ≈ 1 Å），
#: 不会把真正不同的位点误并。
SYM_DEDUP_TOL = 2e-3


def expand_symmetry(atoms, symops, tol: float = SYM_DEDUP_TOL):
    """atoms: [(elem,x,y,z,occ,B)] -> 按对称操作展开并去重的结果。

    ``tol`` 见 :data:`SYM_DEDUP_TOL`（分数坐标，默认 2e-3）。
    """
    if not symops or not atoms:
        return list(atoms)
    out = []
    for (elem, x, y, z, occ, B) in atoms:
        for op in symops:
            nx = (op[0][0] + op[0][1] * x + op[0][2] * y + op[0][3] * z) % 1.0
            ny = (op[1][0] + op[1][1] * x + op[1][2] * y + op[1][3] * z) % 1.0
            nz = (op[2][0] + op[2][1] * x + op[2][2] * y + op[2][3] * z) % 1.0
            out.append((elem, nx, ny, nz, occ, B))
    # 去重 (同一等价点只保留一个)
    ded = []
    for (elem, nx, ny, nz, occ, B) in out:
        dup = False
        for (e2, x2, y2, z2, _o2, _b2) in ded:
            if e2 != elem:
                continue
            if (abs(nx - x2) < tol or abs(abs(nx - x2) - 1.0) < tol) and \
               (abs(ny - y2) < tol or abs(abs(ny - y2) - 1.0) < tol) and \
               (abs(nz - z2) < tol or abs(abs(nz - z2) - 1.0) < tol):
                dup = True
                break
        if not dup:
            ded.append((elem, nx, ny, nz, occ, B))
    return ded


def _scan_single_tag(lines: list[str], tag: str) -> str | None:
    """取一个单行标签的值（CIF 允许三种写法，这里全都要认）。

    1. 同行写值：`_chemical_formula_sum 'Co0.1 Li1.03 ... O2'`
    2. `;` 块值：`;` 换行多行 `;` 结尾
    3. loop 数据行：标签出现在 loop_ 里，紧跟一行数据

    **注释行已被调用方剔除**，故注释里出现的同名字样不会被误取
    （内置 NCA_85_10_05/NCA_82_13_05/前驱体 CIF 的表头注释就写了
    "仅改 _chemical_formula_sum 与 TM 位占位"，极易误抓）。
    """
    n = len(lines)
    for idx, line in enumerate(lines):
        s = line.strip()
        if s == tag:
            rest = ""
        elif s.startswith(tag + " "):
            rest = s[len(tag):].strip()
        else:
            continue
        if rest:
            return rest.strip("'\"")
        j = idx + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n:
            return None
        nxt = lines[j].strip()
        if nxt.startswith(";"):
            k = j + 1
            buf = []
            while k < n and not lines[k].strip().startswith(";"):
                buf.append(lines[k].strip())
                k += 1
            return " ".join(buf).strip("'\"")
        if not nxt.startswith("_") and not nxt.startswith("loop"):
            return nxt.strip("'\"")
        return None
    return None


def _parse_cif_lines(lines: list[str], name: str) -> CifStructure:
    """极简但实用的 CIF 解析核心: 取第一个 data_ 块, 解析晶胞与原子位点循环。"""
    # 去注释行 (以 # 开头的整行)
    raw_lines = []
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        raw_lines.append(line)
    lines = raw_lines

    cell = [1.0, 1.0, 1.0, 90.0, 90.0, 90.0]
    atoms = []
    symops = []
    sg_info: dict = {}          # NCA 修改（T4.2）：空间群 H-M / 国际表号

    def _collect_symop(tags, cols):
        rec = dict(zip(tags, cols[: len(tags)]))
        for t in tags:
            if any(t.startswith(s) for s in _SYM_TAGS):
                v = rec.get(t)
                if v:
                    try:
                        symops.append(parse_symop(v))
                    except Exception:
                        pass
                return True
        return False

    i = 0
    n = len(lines)
    in_loop = False
    loop_tags = []
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("data_") and not name:
            name = stripped[5:].strip() or name
            i += 1
            continue
        if stripped.startswith("_cell_length_a"):
            cell[0] = _to_float(stripped.split(None, 1)[1]) or cell[0]
        elif stripped.startswith("_cell_length_b"):
            cell[1] = _to_float(stripped.split(None, 1)[1]) or cell[1]
        elif stripped.startswith("_cell_length_c"):
            cell[2] = _to_float(stripped.split(None, 1)[1]) or cell[2]
        elif stripped.startswith("_cell_angle_alpha"):
            cell[3] = _to_float(stripped.split(None, 1)[1]) or cell[3]
        elif stripped.startswith("_cell_angle_beta"):
            cell[4] = _to_float(stripped.split(None, 1)[1]) or cell[4]
        elif stripped.startswith("_cell_angle_gamma"):
            cell[5] = _to_float(stripped.split(None, 1)[1]) or cell[5]
        # NCA 修改（T4.2）：空间群 H-M 符号与国际表号（单行标签）
        elif stripped.startswith(("_symmetry_space_group_name_H-M",
                                  "_space_group_name_H-M_alt",
                                  "_space_group_name_H-M_full",
                                  "_symmetry_space_group_name_Hall")):
            sg_name = stripped.split(None, 1)
            if len(sg_name) > 1:
                sg_hm = sg_name[1].strip().strip("'\"")
                if sg_hm and sg_hm not in ("?", "."):
                    sg_info["hm"] = sg_hm
        elif stripped.startswith("_symmetry_Int_Tables_number"):
            # 注意：不要用变量名 n —— 它是外层循环的 len(lines)
            num_val = _to_float(stripped.split(None, 1)[1]
                                if len(stripped.split(None, 1)) > 1 else None)
            if num_val:
                sg_info["number"] = int(num_val)
        elif stripped in ("loop_", "loop"):
            in_loop = True
            loop_tags = []
            i += 1
            continue

        if in_loop:
            if stripped.startswith("_"):
                loop_tags.append(stripped)
                i += 1
                continue
            # 数据行: 直到遇到空行 / 新 tag / data_ / 非 loop 数据结束
            if stripped == "":
                in_loop = False
                i += 1
                continue
            # 对称操作循环
            if loop_tags and _collect_symop(loop_tags, _split_cif_line(stripped)):
                i += 1
                continue
            if loop_tags and any(t.startswith("_atom_site") for t in loop_tags):
                cols = _split_cif_line(stripped)
                if len(cols) < len(loop_tags):
                    # 可能是引号或跨行; 简单跳过不足列的行
                    i += 1
                    continue
                rec = dict(zip(loop_tags, cols[: len(loop_tags)]))
                x = _to_float(rec.get("_atom_site_fract_x"))
                y = _to_float(rec.get("_atom_site_fract_y"))
                z = _to_float(rec.get("_atom_site_fract_z"))
                if x is None or y is None or z is None:
                    i += 1
                    continue
                elem = element_from_symbol(rec.get("_atom_site_type_symbol")) or \
                    element_from_symbol(rec.get("_atom_site_label"))
                if elem is None:
                    i += 1
                    continue
                occ = _to_float(rec.get("_atom_site_occupancy")) or 1.0
                uiso = _to_float(rec.get("_atom_site_U_iso_or_equiv"))
                B = (8 * math.pi ** 2 * uiso) if uiso is not None else 0.0
                atoms.append((elem, x, y, z, occ, B))
                i += 1
                continue
            else:
                # 非原子循环 (如对称操作), 忽略
                i += 1
                continue
        i += 1

    if not atoms:
        raise ValueError(f"未能从 CIF 解析出原子位点: {name}")
    n_raw = len(atoms)
    nsym = len(symops)
    if nsym:
        atoms = expand_symmetry(atoms, symops)
    st = CifStructure(name, tuple(cell), atoms)
    st.n_asym = n_raw
    st.n_sym_ops = nsym
    # NCA 修改（T4.2）：把空间群信息挂到结构上（结果卡要用）
    st.spacegroup = sg_info.get("hm")
    st.sg_number = sg_info.get("number")
    # NCA 修改（T5.3）：化学式 + 自述 Z（QPA 定量用）
    st.formula = _scan_single_tag(lines, "_chemical_formula_sum")
    z_decl = _to_float(_scan_single_tag(lines, "_cell_formula_units_Z"))
    st.z_declared = int(z_decl) if z_decl else None
    return st


def parse_cif(path: str | Path) -> CifStructure:
    """解析 CIF 文件 -> CifStructure（含对称展开）。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return _parse_cif_lines(text.splitlines(), p.stem)


def parse_cif_string(text: str, name: str = "builtin") -> CifStructure:
    """从字符串解析 CIF (用于内置结构 / 测试)。"""
    return _parse_cif_lines(text.splitlines(), name)
