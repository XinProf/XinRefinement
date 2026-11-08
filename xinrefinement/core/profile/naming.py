"""物相显示名（v1.6）。

界面上**不直接暴露 CIF 文件名**（``1Entry_96-500-0036`` 这类 COD 编号对
用户没有意义）。统一由本模块给出三种显示口径：

===========  ==========================================================
mode         含义
===========  ==========================================================
``formula``  规整化学式（``O2 Si`` → ``SiO2``）。**默认口径**。
``label``    物相名称（CIF ``_chemical_name_mineral``，如 ``Quartz``）
``file``     CIF 文件名（``CifStructure.name``，仅在需要追溯来源时用）
===========  ==========================================================

化学式规整只做两件安全的事：**紧凑化**（去掉 CIF 里的空格）与**按
「金属 → 非金属 → 阴离子」再分组**（组内保持 CIF 原序）。不改变任何
元素计数，因此不会让 ``O2 Ti0.992`` 这类占位配方失真。

为什么不用「按电负性排序」：COD 的 ``_chemical_formula_sum`` 常按字母序
写（``O4 S Zn``）。只按电负性排会打乱多金属体系的原有顺序（如 NCA 的
``Li Ni Co Mn``），只按字母序又会让 ``O2 Si`` 显示成 ``O2Si``。分三组
再保序，既能把 ``O4 S Zn`` 修成 ``ZnSO4``，又能让 ``Co Li Ni Mn O2``
保持用户熟悉的顺序。
"""
from __future__ import annotations

import re

#: 显示模式（顺序即 GUI 右键菜单顺序）
PHASE_LABEL_MODES: tuple[str, ...] = ("formula", "label", "file")
#: 默认模式：化学式。用户要求「默认都是优选化学式」。
DEFAULT_PHASE_LABEL_MODE = "formula"

#: 模式的中文名（GUI 菜单/列头用）
MODE_TEXT: dict[str, str] = {
    "formula": "化学式",
    "label": "物相名称",
    "file": "CIF 文件名",
}

# 元素分组：金属(0) → 非金属/类金属(1) → 阴离子(2)。
# 未知元素给 1（小组默认，等同「保持原位置」）。
_METALS = frozenset("""
Li Na K Rb Cs Fr Be Mg Ca Sr Ba Ra
Sc Y Ti Zr Hf V Nb Ta Cr Mo W Mn Tc Re Fe Ru Os Co Rh Ir Ni Pd Pt
Cu Ag Au Zn Cd Hg Al Ga In Tl Sn Pb Bi Po La Ce Pr Nd Pm Sm Eu Gd
Tb Dy Ho Er Tm Yb Lu Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr
""".split())
_NONMETALS = frozenset("H B C Si Ge N P As Sb S Se Te".split())
_ANIONS = frozenset("O F Cl Br I At".split())

_TOKEN = re.compile(r"([A-Z][a-z]?)([0-9]*\.?[0-9]*)")
_GROUP = {"metal": 0, "nonmetal": 1, "anion": 2}


def _group_of(element: str) -> int:
    if element in _METALS:
        return _GROUP["metal"]
    if element in _ANIONS:
        return _GROUP["anion"]
    if element in _NONMETALS:
        return _GROUP["nonmetal"]
    return _GROUP["nonmetal"]


def _fmt_count(n: float) -> str:
    """计数格式化：1 省略；整数写整数；小数取最短可逆表示。"""
    if abs(n - 1.0) < 1e-12:
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:g}"


def normalize_formula(formula: str | None) -> str | None:
    """把 CIF 化学式规整成惯用紧凑写法。

    ``'O2 Si'`` → ``'SiO2'``、``'O2 Ti0.992'`` → ``'Ti0.992O2'``、
    ``'O4 S Zn'`` → ``'ZnSO4'``、``'Ca F2'`` → ``'CaF2'``。

    解析不出元素（含括号、占位符 ``?`` 等）时只做紧凑化，**绝不臆测**。
    """
    if not formula:
        return None
    src = str(formula).strip().strip("'\"")
    if not src:
        return None
    parts = _TOKEN.findall(src)
    # 必须吃满整串（允许空白），否则说明有不认识的写法，退回紧凑化
    if not parts or _TOKEN.sub("", src).strip():
        return "".join(src.split())

    counts: dict[str, float] = {}
    order: list[str] = []
    for element, raw in parts:
        try:
            n = float(raw) if raw not in ("", ".") else 1.0
        except ValueError:
            return "".join(src.split())
        if element not in counts:
            counts[element] = 0.0
            order.append(element)
        counts[element] += n

    # 稳定排序：组号为主键，原序为次键（sorted 本身稳定，故只需组号）
    ordered = sorted(order, key=_group_of)
    return "".join(f"{el}{_fmt_count(counts[el])}" for el in ordered)


def phase_label(struct, mode: str = DEFAULT_PHASE_LABEL_MODE) -> str:
    """按 ``mode`` 给出物相显示名；任一口径缺失时逐级回落。

    回落链：``formula`` → ``label`` → ``file``，保证永远有可显示的字串。
    """
    if struct is None:
        return ""
    file_name = str(getattr(struct, "name", "") or "")
    formula = normalize_formula(getattr(struct, "formula", None))
    label = (getattr(struct, "name_mineral", None) or "").strip() or None

    if mode == "file":
        return file_name or label or formula or ""
    if mode == "label":
        return label or formula or file_name
    return formula or label or file_name


def phase_labels(structs, mode: str = DEFAULT_PHASE_LABEL_MODE) -> list[str]:
    """批量取显示名（保持输入顺序）。"""
    return [phase_label(s, mode) for s in structs]


def label_map(structs, mode: str = DEFAULT_PHASE_LABEL_MODE) -> dict[str, str]:
    """``CifStructure.name`` → 显示名 的映射。

    结果表、标记条、对话框都拿 ``name`` 作键（``PhaseInfo.name`` 也是它），
    需要显示时统一查这张表。同名相后写覆盖前写（GUI 导入时已去重）。
    """
    return {str(s.name): phase_label(s, mode) for s in structs}
