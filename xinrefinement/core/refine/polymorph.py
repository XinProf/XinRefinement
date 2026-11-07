"""多型建议：把「ΔB_iso 撞界 + 化学式/空间群匹配」翻译成可试用动作。

为什么需要
----------
``solve()`` 在 ΔB_iso 顶到上界时会告警「可能是该相结构模型与样品不符
（多型/占位/无序）」，但用户拿到这句话**没法直接行动**：得自己去外面找
另一个多型的 CIF，还要确认空间群、化学式、原子数都对得上。

实测支撑（样 7，2026-11-07）：用户给的方石英是高温 **β（Fd-3m）**，而样品
实际是低温 **α（P4₁2₁2）**。端到端完整配方 14.689 → **14.031**（−0.66 pt），
且 ΔB_iso 撞界同时消失（该相 4.10 → 1.93）。这是纯结构修正，不是把 Rwp
「调」下去的过拟合手段——同一份数据、同一套参数链，只换多型。

红线
----
**只建议，不自动改**用户的 CIF。结构模型属于实验事实（合成温度、相变史），
软件无权替用户判定。本模块只产出建议与「替换后的相列表」，由调用方（GUI
按钮 / CLI 提示）显式触发。

触发条件（三个同时满足，宁可不报也不误报）
------------------------------------------
1. 该相 ΔB_iso **顶到上界**（过拟合信号，说明模型在硬撑强度失配）
2. 该相化学式与候选相同（归一化后逐个元素计数比对）
3. 该相空间群等于候选的「基线多型」空间群（如 β 方石英 Fd-3m）

仅看 ΔB_iso 会误报：7 样复测里 4 个样都有相撞界，绝大多数是织构/标度吸收，
不是多型问题。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


def _data_dir() -> Path:
    """内置数据目录（源码树与 PyInstaller 冻结产物都适用）。

    冻结产物把 ``xinrefinement/data`` 放在 ``_internal/`` 下，模块
    ``__file__`` 也在 ``_internal/xinrefinement/...``，两者同源；onefile
    形态下则要查 ``sys._MEIPASS``。先查目录是否存在，避免打包后才炸。
    """
    cands = [Path(__file__).resolve().parents[2] / "data"]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(Path(base) / "xinrefinement" / "data")
    for c in cands:
        if c.is_dir():
            return c
    return cands[0]


DATA_DIR = _data_dir()


@dataclass(frozen=True)
class PolymorphCandidate:
    """一个可替换的多型候选（内置 CIF）。"""

    key: str
    label: str                  # 给用户看的名字
    cif_file: str               # 内置 CIF 文件名（相对 xinrefinement/data）
    formula: str                # 归一化化学式，如 "O2Si"
    #: 触发用的「基线多型」空间群（归一化、小写、去空格），命中才报
    base_spacegroups: tuple[str, ...]
    gain_note: str              # 实测收益说明（透明化，别让用户盲选）

    @property
    def path(self) -> Path:
        return DATA_DIR / self.cif_file


#: 候选表。新增多型只需加一行 + 放一个内置 CIF。
CANDIDATES: tuple[PolymorphCandidate, ...] = (
    PolymorphCandidate(
        key="cristobalite_alpha",
        label="α-方石英（P4₁2₁2，低温相）",
        cif_file="cristobalite_alpha.cif",
        formula="O2Si",
        base_spacegroups=("fd-3m",),
        gain_note="实测样 7：β(Fd-3m)→α(P4₁2₁2) 端到端 14.689→14.031%"
                  "（−0.66 pt），且该相 ΔB_iso 撞界消失",
    ),
)


@dataclass(frozen=True)
class Suggestion:
    """一条针对具体相的建议。"""

    phase_name: str
    candidate: PolymorphCandidate
    reason: str

    @property
    def action_text(self) -> str:
        return f"试用 {self.candidate.label}"


def formula_key(text: str | None) -> str:
    """把 ``'O2 Si'`` / ``'Si O2'`` / ``'SiO2'`` 统一成 ``'O2Si'``。

    只做「元素 + 计数」的规范化排序，不判断是不是合法化学式；无法解析时
    返回空串（调用方据此放弃匹配，宁可不报）。
    """
    if not text:
        return ""
    tokens = re.findall(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)", str(text))
    if not tokens:
        return ""
    counts: dict[str, float] = {}
    for el, num in tokens:
        try:
            n = float(num) if num else 1.0
        except ValueError:
            n = 1.0
        counts[el] = counts.get(el, 0.0) + n
    return "".join(f"{el}{'' if abs(counts[el] - 1.0) < 1e-9 else _fmt(counts[el])}"
                   for el in sorted(counts))


def _fmt(v: float) -> str:
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"


def spacegroup_key(text: str | None) -> str:
    """空间群符号归一化：小写、去空格与下划线（``'F d -3 m'`` → ``'fd-3m'``）。"""
    if not text:
        return ""
    return re.sub(r"[\s_]", "", str(text)).lower()


def suggest(result, phases) -> list[Suggestion]:
    """按「撞界 + 化学式 + 空间群」三条件给出多型建议（可为空）。

    ``result`` 需有 ``params.b_iso``；``phases`` 为当前 ``CifStructure`` 列表。
    """
    from xinrefinement.core.refine.nonlinear import BISO_BOUNDS

    b_iso = getattr(getattr(result, "params", None), "b_iso", None) or {}
    if not b_iso:
        return []
    hi = float(BISO_BOUNDS[1])
    by_name = {st.name: st for st in phases}
    out: list[Suggestion] = []
    for name, value in sorted(b_iso.items()):
        if float(value) < hi - 1e-6:
            continue
        st = by_name.get(name)
        if st is None:
            continue
        f_key = formula_key(getattr(st, "formula", None))
        sg_key = spacegroup_key(getattr(st, "spacegroup", None))
        for cand in CANDIDATES:
            if f_key != cand.formula:
                continue
            if sg_key not in cand.base_spacegroups:
                continue
            out.append(Suggestion(
                phase_name=name, candidate=cand,
                reason=(f"{name} 的 ΔB_iso 顶到上界 {hi:g} Å²，"
                        f"化学式 {f_key}、空间群 {sg_key} 与该多型的"
                        f"高温/基线型一致——先怀疑多型不符，"
                        f"而不是温度因子")))
    return out


def apply_suggestion(phases, suggestion: Suggestion):
    """返回替换后的相列表（新对象，不改入参）。

    相名沿用原相，保证结果表、配方消息、QPA 里的键都能对上；其余全部取
    内置 CIF 的晶胞与原子坐标。
    """
    from xinrefinement.core.profile.cif import parse_cif

    new_st = parse_cif(suggestion.candidate.path)
    new_st.name = suggestion.phase_name
    out = list(phases)
    for i, st in enumerate(out):
        if st.name == suggestion.phase_name:
            out[i] = new_st
            break
    else:
        raise KeyError(f"相 {suggestion.phase_name!r} 不在当前相列表里")
    return out


def builtin_cif(key: str) -> Path:
    """按候选 key 取内置 CIF 路径（找不到抛 KeyError）。"""
    for cand in CANDIDATES:
        if cand.key == key:
            return cand.path
    raise KeyError(f"未知多型候选: {key!r}")
