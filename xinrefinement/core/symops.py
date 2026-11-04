"""P1.1 · 空间群对称操作（spglib 封装）。

与 :mod:`xinrefinement.core.symmetry` 的分工：
- ``symmetry.py``：H-M 符号 → 晶系/点群/劳厄群/布拉维（元数据，NCA 版）。
- 本模块：空间群 → **对称操作矩阵** → 全晶胞原子展开 / Wyckoff 位识别。

为什么叫 ``symops.py`` 而不是 plan 里的 ``symmetry/ops.py``
------------------------------------------------------------
``core/symmetry.py`` 是 P0 落地的**单文件模块**（被 16 项 symmetry 测试依赖），
同目录不能同时存在 ``symmetry.py`` 与 ``symmetry/`` 包。按最小变更原则，P1
不搬运既有模块，本模块以扁平命名落地；到 P1.0c 统一整理目录时再一并归置。

spglib 2.7 口径（实测，勿按旧版记忆）
------------------------------------
- ``hall_number`` (1..530) **不是** ITA 编号 (1..230)；例：hall 419 → ITA 136。
  映射必须走 ``spglib.get_spacegroup_type(h).number``。
- ``get_spacegroup_type(h)`` 返回 ``SpaceGroupType``，字段为
  ``international`` / ``international_short`` / ``international_full`` /
  ``hall_symbol`` / ``choice`` / ``number``（**无** ``hm_symbol``）。
- ``get_symmetry_from_database(h)`` 返回 ``{"rotations": (N,3,3) int,
  "translations": (N,3) float}``，作用于**分数坐标**：``r' = R·r + t``。
  其行向量正好对应家族 ``parse_symop`` 的 ``(c, ax, ay, az)`` 格式。

设置 / 原点选择
---------------
同一 ITA 编号可能有多个 hall 设置（Pnma/Pbnm 等轴置换、R-3m 六方 H / 菱方 R）。
CIF 显式给出 ``_symmetry_equiv_pos_as_xyz`` 时应**优先用 CIF 自带的 symop**
（家族 ``cif.parse_symop`` 已有，展开结果不会因设置不同而错位）；只有 CIF 缺
symop 时才用本模块，并通过 ``setting`` 参数选择 hall 设置。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

try:
    import spglib
except ImportError as exc:  # pragma: no cover - 依赖缺失时给明确诊断
    raise ImportError("P1.1 需要 spglib>=2.5：pip install spglib") from exc

HALL_MIN, HALL_MAX = 1, 530


@dataclass(frozen=True)
class SpaceGroupChoice:
    """一个 hall 设置（供用户/调用方选择）。"""

    hall_number: int
    number: int
    international_short: str
    international_full: str
    hall_symbol: str
    choice: str


@dataclass(frozen=True)
class SymOps:
    """一组空间群对称操作。"""

    number: int
    hm: str
    hall_number: int
    hall_symbol: str
    rotations: np.ndarray       # (N, 3, 3) int
    translations: np.ndarray    # (N, 3) float

    @property
    def n_ops(self) -> int:
        return int(self.rotations.shape[0])

    def to_family_symops(self) -> list[list[tuple[float, float, float, float]]]:
        """转成家族 ``cif.expand_symmetry`` 需要的 symop 格式。

        每个 op 为 3 行 ``(c, ax, ay, az)``，表示
        ``new = c + ax·x + ay·y + az·z``（分数坐标）。
        """
        out: list[list[tuple[float, float, float, float]]] = []
        for r, t in zip(self.rotations, self.translations):
            out.append([
                (float(t[0]), float(r[0, 0]), float(r[0, 1]), float(r[0, 2])),
                (float(t[1]), float(r[1, 0]), float(r[1, 1]), float(r[1, 2])),
                (float(t[2]), float(r[2, 0]), float(r[2, 1]), float(r[2, 2])),
            ])
        return out


@lru_cache(maxsize=1)
def _all_types() -> tuple[SpaceGroupChoice, ...]:
    """枚举全部 530 个 hall 设置（一次，缓存）。"""
    out: list[SpaceGroupChoice] = []
    for h in range(HALL_MIN, HALL_MAX + 1):
        t = spglib.get_spacegroup_type(h)
        if t is None:
            continue
        out.append(SpaceGroupChoice(
            hall_number=int(h), number=int(t.number),
            international_short=str(t.international_short or ""),
            international_full=str(t.international_full or ""),
            hall_symbol=str(t.hall_symbol or ""),
            choice=str(t.choice or ""),
        ))
    return tuple(out)


def _norm(s: str) -> str:
    """H-M 符号归一化：去空格/引号、统一大小写，便于比较。"""
    return re.sub(r"[\s'\"_]", "", s or "").lower()


def hall_candidates(number: int | None = None,
                    hm: str | None = None) -> list[SpaceGroupChoice]:
    """列出符合 ITA 编号或 H-M 符号的所有 hall 设置。

    解析优先级：ITA 编号 > H-M 短式/全式符号。H-M 符号先经家族
    ``symmetry.lookup`` 归一（容忍 ``P 1 21/n 1`` 这类全式与别名），
    失败再直接对 spglib 的短式/全式做归一化匹配。
    """
    if number is None and not hm:
        raise ValueError("需给定 number 或 hm")

    if number is None:
        from xinrefinement.core.symmetry import lookup
        try:
            number = int(lookup(hm).number)  # type: ignore[arg-type]
        except Exception:
            number = None

    pool = _all_types()
    if number is not None:
        hits = [c for c in pool if c.number == int(number)]
    else:
        key = _norm(hm or "")
        hits = [c for c in pool
                if _norm(c.international_short) == key
                or _norm(c.international_full) == key]
    if not hits:
        raise KeyError(f"未找到空间群设置: number={number!r} hm={hm!r}")
    return hits


def match_setting(choices: list[SpaceGroupChoice],
                  setting: str | None) -> SpaceGroupChoice:
    """从候选里挑一个 hall 设置。

    ``setting`` 支持：
    - ``"H"`` / ``"R"``：六方 / 菱方设置（R-3m 等）。**spglib 2.7 实测**：
      该标记在 ``SpaceGroupType.choice`` 字段（``'H'`` / ``'R'``），
      ``hall_symbol`` 里**没有** ``:H`` / ``:R`` 后缀（如 458 的
      ``-R 3 2"``、459 的 ``-P 3* 2``），故不能按 hall_symbol 匹配。
    - ``"standard"`` 或 ``None``：取 hall 编号最小者（spglib 的标准设置）；
    - 整数字符串：直接指定 hall_number。
    """
    if setting is None or setting.lower() in ("standard", "std", ""):
        return min(choices, key=lambda c: c.hall_number)
    if setting.isdigit():
        h = int(setting)
        for c in choices:
            if c.hall_number == h:
                return c
        raise KeyError(f"hall_number={h} 不在候选设置中")
    key = setting.upper()
    tagged = [c for c in choices if c.choice.strip().upper() == key]
    if not tagged and key in ("H", "R"):
        # 兜底：部分 spglib 版本把设置放在 hall_symbol 尾部
        tagged = [c for c in choices if f":{key}" in c.hall_symbol.upper()]
    if not tagged:
        raise KeyError(
            f"未找到设置 {setting!r}（候选 choice: "
            f"{[(c.hall_number, c.choice) for c in choices]}）")
    return min(tagged, key=lambda c: c.hall_number)


def symops_from_spg(number: int | None = None, hm: str | None = None,
                    hall_number: int | None = None,
                    setting: str | None = None) -> SymOps:
    """由 ITA 编号 / H-M 符号 / hall 编号取得对称操作。

    ``hall_number`` 显式给定最优先（跳过候选匹配）。其余走
    :func:`hall_candidates` + :func:`match_setting`。
    """
    if hall_number is not None:
        if not (HALL_MIN <= int(hall_number) <= HALL_MAX):
            raise ValueError(f"hall_number 必须在 [{HALL_MIN},{HALL_MAX}]")
        t = spglib.get_spacegroup_type(int(hall_number))
        if t is None:
            raise KeyError(f"未知 hall_number={hall_number}")
        choice = SpaceGroupChoice(
            hall_number=int(hall_number), number=int(t.number),
            international_short=str(t.international_short or ""),
            international_full=str(t.international_full or ""),
            hall_symbol=str(t.hall_symbol or ""), choice=str(t.choice or ""))
    else:
        choice = match_setting(hall_candidates(number, hm), setting)

    data = spglib.get_symmetry_from_database(choice.hall_number)
    if data is None:
        raise KeyError(f"hall_number={choice.hall_number} 无对称操作数据")
    return SymOps(
        number=choice.number,
        hm=choice.international_short or choice.international_full,
        hall_number=choice.hall_number,
        hall_symbol=choice.hall_symbol,
        rotations=np.asarray(data["rotations"], dtype=np.int64),
        translations=np.asarray(data["translations"], dtype=np.float64),
    )


def expand_unit_cell(atoms, ops: SymOps | list, tol: float = 1e-4):
    """把不对称单位原子展开成全晶胞原子。

    ``ops`` 可为 :class:`SymOps` 或家族 symop 格式列表；内部统一转成
    家族格式后复用 :func:`xinrefinement.core.profile.cif.expand_symmetry`，
    保证与 P0 已验证的展开逻辑（含去重口径）完全一致。
    """
    from xinrefinement.core.profile.cif import expand_symmetry
    fam = ops.to_family_symops() if isinstance(ops, SymOps) else ops
    return expand_symmetry(atoms, fam, tol=tol)


def _periodic_delta(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """分数坐标差在周期边界下的最小绝对差。"""
    d = np.abs(np.asarray(a) - np.asarray(b)) % 1.0
    return np.minimum(d, 1.0 - d)


def site_symmetry_rotations(ops: SymOps, xyz,
                            tol: float = 1e-4) -> list[np.ndarray]:
    """返回把 ``xyz`` 映回自身（模 1）的对称操作旋转矩阵（位点稳定子）。"""
    p = np.asarray(xyz, dtype=np.float64)
    out: list[np.ndarray] = []
    for r, t in zip(ops.rotations, ops.translations):
        image = (r @ p + t) % 1.0
        if float(np.max(_periodic_delta(image, p))) < tol:
            out.append(np.asarray(r, dtype=np.float64))
    return out


def free_coordinate_dims(ops: SymOps, xyz, tol: float = 1e-4) -> int:
    """Wyckoff 位点的**自由坐标维度**（P1.3 原子坐标精修的前置）。

    位点稳定子要求 ``(R - I)·δ = 0``；把所有稳定子旋转矩阵堆成 M，
    自由维度 = ``3 - rank(M)``，即 M 的零空间维度。

    - 一般位（稳定子只有恒等）：M=0 → 3 维自由；
    - 特殊位（如反演中心上的 (0,0,0)）：R=-I → rank 3 → 0 维（坐标固定）；
    - 镜面/轴上位置：rank 1 或 2 → 2 或 1 维自由。
    """
    mats = site_symmetry_rotations(ops, xyz, tol)
    if not mats:
        return 3
    m = np.vstack([r - np.eye(3) for r in mats])
    rank = int(np.linalg.matrix_rank(m, tol=1e-8))
    return 3 - rank


def free_coordinate_basis(ops: SymOps, xyz,
                          tol: float = 1e-4) -> np.ndarray:
    """返回自由坐标方向的正交基，shape ``(3, n_free)``；列即允许的位移方向。

    P1.3 对每个特殊位只对自由分量建变量，联动分量用这些基向量表达。
    """
    mats = site_symmetry_rotations(ops, xyz, tol)
    m = (np.vstack([r - np.eye(3) for r in mats])
         if mats else np.zeros((3, 3)))
    _u, s, vh = np.linalg.svd(m)
    rank = int(np.count_nonzero(s > 1e-8))
    return vh[rank:].T
