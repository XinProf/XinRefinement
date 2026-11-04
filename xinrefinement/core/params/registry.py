"""P1.0b · 声明式参数注册表（双轨阶段）。

目的：把 ``nonlinear._pack/_unpack/_bounds`` 里**写死的开关顺序**变成可声明、
可查询、可分组、可回填 e.s.d. 的 ``ParameterRegistry``，为 P1.0c 全面替换、
P2 参数模块、P3 导航式 GUI 提供统一底座。

双轨约定（本卡不修改 ``nonlinear.py``）
--------------------------------------
registry 生成的 pack 顺序/取值/bounds 必须与现有 ``_pack/_unpack/_bounds``
**逐位一致**，由 ``tests/test_registry.py`` 逐开关组合断言。P1.0c 才把
``nonlinear.py`` 的调用点切到 registry 并删除旧路径。

顺序（与 ``_pack`` 严格一致，勿调整）
------------------------------------
``zero → U,V,W → eta → asym → bfactor → 每相 (fa,fc) → 每相 PO r(sorted) → X → Y``

其中 X/Y 在 ``_unpack`` 里是**从向量末端倒读**的，registry 保持同一约定。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from xinrefinement.core.profile.forward import MIN_W, ProfileParams
from xinrefinement.core.refine import nonlinear as nl


@dataclass(frozen=True)
class Parameter:
    """一个可精修参数（对外只读快照）。"""

    key: str                       # "global.zero" / "phase0.cell.a" / "phase0.atom3.B"
    owner: str                     # "global" | "phase" | "atom"
    group: str                     # zero/profile/cell/po/micro/... （导航步骤归属）
    bounds: tuple[float, float]
    refine: bool = True
    histogram: int | str = "all"   # v1 单谱恒 "all"；为 v2 多谱联合预留
    value: float = 0.0
    esd: float | None = None       # 收敛后由 P1.5 回填

    @property
    def label(self) -> str:
        return self.key


@dataclass(frozen=True)
class _Slot:
    """内部槽位：描述向量中的某一维如何读写。"""

    key: str
    owner: str
    group: str
    bounds: tuple[float, float]
    get: Callable[[ProfileParams, list, dict | None], float]
    set: Callable[[ProfileParams, list, dict | None, float],
                  tuple[ProfileParams, list, dict | None]]
    histogram: int | str = "all"


def _g_prm(field: str):
    return lambda prm, cell, po: float(getattr(prm, field))


def _s_prm(field: str, clamp_w: bool = False):
    def _fn(prm, cell, po, v):
        if clamp_w:
            v = max(float(v), MIN_W)
        return replace(prm, **{field: float(v)}), cell, po
    return _fn


def _g_cell(i: int, j: int):
    return lambda prm, cell, po: float(cell[i][j])


def _s_cell(i: int, j: int):
    def _fn(prm, cell, po, v):
        row = list(cell[i])
        row[j] = float(v)
        cell[i] = (row[0], row[1])
        return prm, cell, po
    return _fn


def _g_po(name: str):
    return lambda prm, cell, po: float(po[name][3]) if po else 1.0


def _s_po(name: str):
    def _fn(prm, cell, po, v):
        e = po[name]
        po[name] = (e[0], e[1], e[2], float(v))
        return prm, cell, po
    return _fn


def build_registry_from_config(cfg: nl.RefineConfig, prm: ProfileParams,
                               n_phase: int = 1,
                               po_names: list[str] | None = None
                               ) -> "ParameterRegistry":
    """按 ``cfg`` 开关构造 registry（顺序与 ``_pack`` 一致）。"""
    slots: list[_Slot] = []

    def add(key, owner, group, bounds, getter, setter):
        slots.append(_Slot(key, owner, group, bounds, getter, setter))

    if cfg.refine_zero:
        add("global.zero", "global", "zero", nl.ZERO_BOUNDS,
            _g_prm("zero"), _s_prm("zero"))
    if cfg.refine_uvw:
        add("global.profile.U", "global", "profile", nl.UVW_BOUNDS,
            _g_prm("U"), _s_prm("U"))
        add("global.profile.V", "global", "profile", nl.V_BOUNDS,
            _g_prm("V"), _s_prm("V"))
        add("global.profile.W", "global", "profile", (MIN_W, nl.UVW_BOUNDS[1]),
            _g_prm("W"), _s_prm("W", clamp_w=True))
    if cfg.refine_eta:
        add("global.profile.eta", "global", "profile", nl.ETA_BOUNDS,
            _g_prm("eta"), _s_prm("eta"))
    if cfg.refine_asym:
        add("global.profile.asym", "global", "profile", nl.ASYM_BOUNDS,
            _g_prm("asym"), _s_prm("asym"))
    if cfg.refine_bfactor:
        add("global.profile.bfactor", "global", "profile", nl.BFACTOR_BOUNDS,
            _g_prm("bfactor"), _s_prm("bfactor"))
    if cfg.refine_cell:
        for i in range(n_phase):
            for j, nm in enumerate(("a", "c")):
                add(f"phase{i}.cell.{nm}", "phase", "cell", nl.CELL_BOUNDS,
                    _g_cell(i, j), _s_cell(i, j))
    if cfg.refine_po and po_names:
        for name in sorted(po_names):
            add(f"phase[{name}].po.r", "phase", "po", nl.PO_BOUNDS,
                _g_po(name), _s_po(name))
    if cfg.refine_strain:
        add("global.micro.X", "global", "micro", nl.STRAIN_BOUNDS,
            _g_prm("X"), _s_prm("X"))
    if cfg.refine_size:
        add("global.micro.Y", "global", "micro", nl.SIZE_BOUNDS,
            _g_prm("Y"), _s_prm("Y"))

    return ParameterRegistry(tuple(slots), n_phase=n_phase,
                             po_names=tuple(sorted(po_names or [])))


class ParameterRegistry:
    """有序参数注册表：pack / unpack / bounds / 分组 / e.s.d. 回填。"""

    def __init__(self, slots: tuple[_Slot, ...], n_phase: int = 1,
                 po_names: tuple[str, ...] = ()):
        self._slots = slots
        self._n_phase = n_phase
        self._po_names = po_names
        self._esd: np.ndarray | None = None

    @property
    def size(self) -> int:
        return len(self._slots)

    def labels(self) -> list[str]:
        return [s.key for s in self._slots]

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = np.array([s.bounds[0] for s in self._slots], dtype=np.float64)
        hi = np.array([s.bounds[1] for s in self._slots], dtype=np.float64)
        return lo, hi

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for s in self._slots:
            out.setdefault(s.group, []).append(s.key)
        return out

    def pack(self, prm: ProfileParams,
             cell_scales: list[tuple[float, float]] | None = None,
             po_r: dict | None = None) -> np.ndarray:
        """按槽位顺序打包（与 ``nonlinear._pack`` 逐位一致）。"""
        cell = [tuple(p) for p in (cell_scales or [(1.0, 1.0)] * self._n_phase)]
        po = dict(po_r) if po_r else None
        return np.array([s.get(prm, cell, po) for s in self._slots],
                        dtype=np.float64)

    def unpack(self, x: np.ndarray, base: ProfileParams,
               cell_scales: list[tuple[float, float]] | None = None,
               po_r: dict | None = None
               ) -> tuple[ProfileParams, list[tuple[float, float]], dict | None]:
        """由向量重建参数（与 ``nonlinear._unpack`` 逐位一致）。

        X/Y 从向量末端倒读、PO 按 sorted 顺序正读，与引擎层同一约定。
        """
        x = np.asarray(x, dtype=np.float64)
        if x.size != self.size:
            raise ValueError(f"向量长度 {x.size} 与槽位数 {self.size} 不符")
        prm = base
        cell = [tuple(p) for p in (cell_scales or [(1.0, 1.0)] * self._n_phase)]
        po = dict(po_r) if po_r else None

        # X/Y 在 _unpack 中从末端倒读；其余按槽位正序。这里把 X/Y 槽位的
        # 值按末端位置预取，保证与引擎层逐位一致（含只开其一的情形）。
        tail: dict[int, float] = {}
        idx = len(x)
        if any(s.key == "global.micro.Y" for s in self._slots):
            idx -= 1
            tail[self._find_key("global.micro.Y")] = float(x[idx])
        if any(s.key == "global.micro.X" for s in self._slots):
            idx -= 1
            tail[self._find_key("global.micro.X")] = float(x[idx])

        for i, s in enumerate(self._slots):
            v = tail.get(i, float(x[i]))
            prm, cell, po = s.set(prm, cell, po, v)
        return prm, [(float(a), float(b)) for a, b in cell], po

    def _find_key(self, key: str) -> int:
        for i, s in enumerate(self._slots):
            if s.key == key:
                return i
        return -1

    def parameters(self) -> list[Parameter]:
        """导出只读快照列表（含已回填的 e.s.d.）。"""
        out = []
        for i, s in enumerate(self._slots):
            esd = None if self._esd is None else float(self._esd[i])
            out.append(Parameter(
                key=s.key, owner=s.owner, group=s.group, bounds=s.bounds,
                refine=True, histogram=s.histogram, esd=esd))
        return out

    def set_esd(self, esd: np.ndarray) -> None:
        """P1.5：回填 e.s.d.（长度须等于向量维数）。"""
        a = np.asarray(esd, dtype=np.float64).ravel()
        if a.size != self.size:
            raise ValueError(f"e.s.d. 长度 {a.size} 与槽位数 {self.size} 不符")
        self._esd = a.copy()
