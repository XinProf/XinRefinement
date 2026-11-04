"""空间群元数据（T4.2 · 新建，非 vendor）。

把空间群符号映射到 (晶系, 点群, 劳厄群, 布拉维格子)：
- `R -3 m` -> 三方 / -3m / -3m / hR（层状 NCA 的 R-3m #166）

权威来源：`nca/data/spacegroups.json`（International Tables Vol.A 的标准
数据）。未登记的符号走**规则推导兜底**（H-M 符号 → 点群 → 劳厄类/
晶系/布拉维格子），推导不出则抛 KeyError 并提示补表 —— 宁可报错，
也不要给一个错的晶系（晶系错了，结果卡的点群/劳厄群就全不可信）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: 数据表路径
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "spacegroups.json"

#: 32 个点群 -> (晶系, 劳厄类)
_POINT_GROUP_TABLE: dict[str, tuple[str, str]] = {
    "-1": ("triclinic", "-1"),
    "1": ("triclinic", "-1"),
    "2": ("monoclinic", "2/m"),
    "m": ("monoclinic", "2/m"),
    "2/m": ("monoclinic", "2/m"),
    "222": ("orthorhombic", "mmm"),
    "mm2": ("orthorhombic", "mmm"),
    "mmm": ("orthorhombic", "mmm"),
    "4": ("tetragonal", "4/mmm"),
    "-4": ("tetragonal", "4/mmm"),
    "4/m": ("tetragonal", "4/mmm"),
    "422": ("tetragonal", "4/mmm"),
    "4mm": ("tetragonal", "4/mmm"),
    "-42m": ("tetragonal", "4/mmm"),
    "4/mmm": ("tetragonal", "4/mmm"),
    "3": ("trigonal", "-3m"),
    "-3": ("trigonal", "-3m"),
    "32": ("trigonal", "-3m"),
    "3m": ("trigonal", "-3m"),
    "-3m": ("trigonal", "-3m"),
    "6": ("hexagonal", "6/mmm"),
    "-6": ("hexagonal", "6/mmm"),
    "6/m": ("hexagonal", "6/mmm"),
    "622": ("hexagonal", "6/mmm"),
    "6mm": ("hexagonal", "6/mmm"),
    "-6m2": ("hexagonal", "6/mmm"),
    "6/mmm": ("hexagonal", "6/mmm"),
    "23": ("cubic", "m-3m"),
    "m-3": ("cubic", "m-3m"),
    "432": ("cubic", "m-3m"),
    "-43m": ("cubic", "m-3m"),
    "m-3m": ("cubic", "m-3m"),
}

#: 晶系中文名
_SYSTEM_ZH = {
    "triclinic": "三斜", "monoclinic": "单斜", "orthorhombic": "正交",
    "tetragonal": "四方", "trigonal": "三方", "hexagonal": "六方",
    "cubic": "立方",
}

#: 布拉维格子前缀（Pearson-Bravais 首字母 = 晶系）
_BRAVIS_PREFIX = {
    "triclinic": "a", "monoclinic": "m", "orthorhombic": "o",
    "tetragonal": "t", "trigonal": "h", "hexagonal": "h", "cubic": "c",
}


@dataclass(frozen=True)
class SpaceGroupInfo:
    """一个空间群的元数据。"""

    hm: str                    # H-M 符号（标准短式）
    number: int | None         # 国际表号
    crystal_system: str        # triclinic / monoclinic / ... / cubic
    crystal_system_zh: str     # 三斜 / 单斜 / ...
    point_group: str           # 点群，如 -3m
    laue_group: str            # 劳厄群，如 -3m
    bravais: str               # 布拉维格子，如 hR
    derived: bool = False      # True = 由规则推导（未登记于数据表）

    def as_dict(self) -> dict:
        return {
            "space_group": self.hm,
            "space_group_number": self.number,
            "crystal_system": self.crystal_system,
            "crystal_system_zh": self.crystal_system_zh,
            "point_group": self.point_group,
            "laue_group": self.laue_group,
            "bravais_lattice": self.bravais,
            "derived": self.derived,
        }


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["space_groups"]


#: H-M **全式 → 短式** 别名（COD 原始件普遍写全式，如 'P 1 21/n 1'）。
#:
#: 为什么必须显式列表而不是写通用归约规则：单斜全式 'L 1 X 1' 与正交
#: 'L 2 2 2' 去掉数字后形近，通用正则容易把不同空间群并成一个 —— 给错
#: 晶系比报错更糟（点群/劳厄群会连带全错）。这里只收本项目入库结构用到的
#: 写法；遇到未收录的全式会走规则兜底，仍失败则抛 KeyError 提示补表。
_HM_ALIAS: dict[str, str] = {
    "P121/n1": "P21/n",      # 三水铝石 Al(OH)3（COD 1200016），#14 的 n 设定
    "P121/c1": "P21/c",      # #14 标准设定
    "C12/c1": "C2/c",        # 残碱 Li2CO3（COD 9008283），#15
    "P1121/a1": "P21/a",     # #14 的 a 设定
}


def normalize_hm(symbol: str) -> str:
    """规范化 H-M 符号：去空格/下划线/设定后缀，全式转短式。

    'R -3 m :H' -> 'R-3m'；'P 21/c' -> 'P21/c'；'P 1 21/n 1' -> 'P21/n'
    """
    s = str(symbol).strip()
    # 去掉设定后缀（:H/:R/:1/:2）与 origin choice 标记
    s = re.sub(r":[A-Za-z0-9]+$", "", s).strip()
    s = s.replace("_", "")
    s = re.sub(r"\s+", "", s)
    if not s:
        return ""
    return _HM_ALIAS.get(s, s)


def _canonical_key(symbol: str) -> str:
    """查表键：去空格、去下划线、去 ':H' 等后缀，保留大小写但忽略 'm'/'c' 之外的写法差异。"""
    s = normalize_hm(symbol)
    # 表里的键形如 "R-3m" / "P21/c" / "Fd-3m"
    return s


@lru_cache(maxsize=1)
def _by_number_map() -> dict[int, str]:
    return {int(v["number"]): k for k, v in _table().items()}


def _bravais_for(system: str, lattice_letter: str) -> str:
    """由晶系 + 中心化字母推出 Pearson-Bravais 简写。"""
    prefix = _BRAVIS_PREFIX.get(system, "")
    centering = {
        "P": "P", "A": "A", "B": "B", "C": "C", "I": "I", "F": "F", "R": "R",
        "H": "P",
    }.get(lattice_letter.upper(), "P")
    if system == "trigonal" and centering == "R":
        return "hR"
    if system in ("trigonal", "hexagonal"):
        centering = "P" if centering in ("P", "H") else centering
    return f"{prefix}{centering}"


def _derive_point_group(symbol: str) -> tuple[str, str] | None:
    """规则兜底：从 H-M 短式推导 (点群, 晶系字母)。

    处理要点：
    - 斜杠左侧 = 主轴（含 2_1/4_2/6_3 等螺旋，数字合并），斜杠右侧 = 镜面
      方向（滑移面在点群中一律记作 m）；
    - 方向位数字（'1'/'2'/'3'…）在点群里丢弃（"P-3m1" -> "-3m"）；
    - 三方 + P 中心化 -> 三方晶系；立方格子的 F/I/P 在 "-3" 情形下点群要
      升级为 m-3m / -43m。
    """
    s = normalize_hm(symbol)
    if not s:
        return None
    lattice = ""
    if s[0].upper() in "PCIFRABH":
        lattice, s = s[0].upper(), s[1:]
    if not s:
        return None
    # 主轴：可选 '-' + 数字（可带尾数 2/3）
    m = re.match(r"^(-?)(\d)([0-9]*)", s)
    if not m:
        return None
    bar, order, _tail = m.groups()
    rest = s[m.end():]
    mirrors = ""
    if rest.startswith("/"):
        rest = rest[1:]
        # 右半段：镜面字母（m/c/n/a/d/e）+ 方向数字
        mirrors = re.sub(r"[0-9]", "", rest)
        mirrors = "".join("m" if ch in "mcnade" else ch for ch in mirrors)
    if bar == "-":
        pg = f"-{order}"
    else:
        pg = order
    if mirrors:
        pg = f"{pg}/{mirrors}"
    elif "/" not in pg and order in ("2", "3", "4", "6") and rest == "":
        pass
    # 三方：'3' 单独出现 -> 3；带镜面 -> 3m / -3m
    if order == "3" and mirrors == "m":
        pg = ("-3m" if bar == "-" else "3m")
    elif order == "3" and not mirrors:
        pg = "-3" if bar == "-" else "3"
    # 立方：F/I 中心化的 -3 轴实际点群更高
    if order == "3" and bar == "-" and lattice in ("F", "I"):
        pg = "m-3m" if lattice == "F" else "m-3"
    return pg, lattice


def lookup(symbol: str) -> SpaceGroupInfo:
    """查空间群元数据。未知符号走规则兜底；兜底失败抛 KeyError。"""
    if symbol is None:
        raise KeyError("空间群符号为空")
    key = _canonical_key(symbol)
    tbl = _table()
    # 直接命中
    if key in tbl:
        v = tbl[key]
        return SpaceGroupInfo(hm=key, number=int(v["number"]),
                              crystal_system=v["crystal_system"],
                              crystal_system_zh=v.get(
                                  "crystal_system_zh",
                                  _SYSTEM_ZH.get(v["crystal_system"], "")),
                              point_group=v["point_group"],
                              laue_group=v["laue_group"],
                              bravais=v["bravais"], derived=False)
    # 忽略大小写再试。**连字符必须保留**：H-M 符号里 "-" 是反演轴，
    # "R-3m"(#166) 与 "R3m"(#160) 是两个不同的空间群 —— 早前把连字符
    # 一起剥掉导致 r-3m 命中 R3m（错误编号）。
    loose = key.lower()
    for k, v in tbl.items():
        if k.lower() == loose:
            return SpaceGroupInfo(hm=k, number=int(v["number"]),
                                  crystal_system=v["crystal_system"],
                                  crystal_system_zh=v.get(
                                      "crystal_system_zh",
                                      _SYSTEM_ZH.get(v["crystal_system"], "")),
                                  point_group=v["point_group"],
                                  laue_group=v["laue_group"],
                                  bravais=v["bravais"], derived=False)
    # 规则兜底
    derived = _derive_point_group(key)
    if derived is None:
        raise KeyError(f"未知空间群符号: {symbol!r}（请补入 nca/data/spacegroups.json）")
    pg, lattice = derived
    if pg not in _POINT_GROUP_TABLE:
        raise KeyError(f"空间群 {symbol!r} 的点群无法确定（推导得 {pg!r}），"
                       "请补入 nca/data/spacegroups.json")
    system, laue = _POINT_GROUP_TABLE[pg]
    return SpaceGroupInfo(hm=key, number=None, crystal_system=system,
                          crystal_system_zh=_SYSTEM_ZH.get(system, system),
                          point_group=pg, laue_group=laue,
                          bravais=_bravais_for(system, lattice or "P"),
                          derived=True)


def lookup_by_number(number: int) -> SpaceGroupInfo:
    """按国际表号查（表内编号 -> 符号 -> 元数据）。"""
    tbl = _by_number_map()
    hm = tbl.get(int(number))
    if hm is None:
        raise KeyError(f"空间群国际表号 {number} 不在数据表中")
    return lookup(hm)


def describe(symbol: str) -> str:
    """一行中文描述（结果卡/界面用）。"""
    info = lookup(symbol)
    return (f"{info.hm}（{info.crystal_system_zh}晶系，"
            f"点群 {info.point_group}，劳厄群 {info.laue_group}，"
            f"布拉维格子 {info.bravais}）")
