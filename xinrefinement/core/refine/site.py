"""P1.3/P1.4 · 不对称单位站点模型 + 原子坐标/B/占位精修。

为什么需要本模块
----------------
``core.profile.cif.parse_cif`` 在解析时**立即把不对称单位展开成全晶胞**，
只留 ``n_asym`` / ``n_sym_ops`` 计数，不保留「哪个原子属于哪个位点」的映射。
坐标精修若直接改展开后的原子，会破坏对称性（等价原子不再联动）。
本模块重新从 CIF 读出**未展开的不对称单位 + symop**，建立位点模型：

- 每个位点用 site symmetry 旋转矩阵 ``(R−I)`` 的**零空间**求自由坐标维度
  （P1.1 的 ``free_coordinate_basis``），只对自由分量建变量；
- 施加位移后用同一组 symop 重新展开，等价原子天然联动；
- B 因子（各向同性）与占位率 occ 也按位点联动。

这是**独立精修引擎**（``refine_sites``），不修改 ``nonlinear.py`` 主路径、
不改 ``RefineConfig`` 默认值 —— 与 P1.2 同一「零回归风险」策略。

参数向量布局（按位点顺序）
--------------------------
对每个不对称位点依次放：``n_free`` 个自由坐标系数 → ``dB`` → ``d_occ``
（相对变化）。全 0 向量 = 原始 CIF 结构。
"""
from __future__ import annotations

import math
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import (
    CifStructure,
    element_from_symbol,
    expand_symmetry,
    parse_symop,
)
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.linear import solve_linear_detail
from xinrefinement.core.refine.lm import lm_minimize
from xinrefinement.core.refine.rfactors import compute_rfactors
from xinrefinement.core.symops import SymOps

#: 参数边界
XYZ_BOUNDS = (-0.05, 0.05)      # 分数坐标系数
B_BOUNDS = (-2.0, 2.0)          # Å² 增量
OCC_BOUNDS = (-0.30, 0.30)      # 相对变化


@dataclass(frozen=True)
class Site:
    """不对称单位中的一个原子位点。"""

    elem: str
    xyz: tuple[float, float, float]
    occ: float
    B: float
    basis: np.ndarray             # (3, n_free) 自由坐标方向的正交基
    n_free: int


@dataclass
class SiteModel:
    """一个物相的不对称单位模型。"""

    name: str
    cell: tuple[float, ...]
    sites: list[Site]
    symops: list                 # family symop 格式（供 expand_symmetry）
    formula: str | None = None
    spacegroup: str | None = None
    sg_number: int | None = None

    @property
    def dims(self) -> list[int]:
        return [s.n_free + 2 for s in self.sites]

    @property
    def n_params(self) -> int:
        return sum(self.dims)

    @property
    def offsets(self) -> list[int]:
        out, acc = [], 0
        for d in self.dims:
            out.append(acc)
            acc += d
        return out

    def to_structure(self, x: np.ndarray) -> CifStructure:
        """由参数向量重建**全晶胞**结构（等价位点联动）。"""
        x = np.asarray(x, dtype=np.float64).ravel()
        if x.size != self.n_params:
            raise ValueError(f"{self.name}: 需 {self.n_params} 个参数，收到 {x.size}")
        atoms = []
        for site, off in zip(self.sites, self.offsets):
            dx = (site.basis @ x[off:off + site.n_free]
                  if site.n_free else np.zeros(3))
            xyz = tuple(float(v) for v in np.asarray(site.xyz) + dx)
            dB = float(x[off + site.n_free])
            d_occ = float(x[off + site.n_free + 1])
            atoms.append((site.elem, xyz[0], xyz[1], xyz[2],
                          site.occ * (1.0 + d_occ), max(0.0, site.B + dB)))
        expanded = expand_symmetry(atoms, self.symops)
        st = CifStructure(self.name, self.cell, expanded)
        st.formula = self.formula
        st.spacegroup = self.spacegroup
        st.sg_number = self.sg_number
        # 关键：forward._PEAKS_CACHE 的键含 id(struct)，而每次评估都新建
        # 结构（同 name/cell/原子数），CPython 地址复用会让新旧结构撞出
        # 相同 id -> 陈旧峰强，坐标/B/occ 变化被缓存吞掉。引擎已为此预留
        # ``_variant`` 盐值钩子，这里按参数向量内容生成稳定盐值。
        st._variant = tuple(float(v) for v in np.round(x, 9))
        return st


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().strip("'\"")
    if not s or s in ("?", ".", "-"):
        return None
    if "(" in s:
        head, _, tail = s.partition("(")
        s = head + (tail.split(")", 1)[1] if ")" in tail else "")
    try:
        return float(s)
    except ValueError:
        return None


def _split(s: str) -> list[str]:
    if "'" in s or '"' in s:
        try:
            return shlex.split(s)
        except ValueError:
            return s.split()
    return s.split()


def family_to_symops(symops: list, number: int | None = None,
                     hm: str | None = None) -> SymOps:
    """把 CIF 的 family symop 格式转成 :class:`SymOps`（供零空间计算）。

    每行 op 为 ``(c, ax, ay, az)``；旋转矩阵行 = (ax, ay, az)，平移 = c。
    """
    rotations, translations = [], []
    for op in symops:
        rotations.append([[op[r][1], op[r][2], op[r][3]] for r in range(3)])
        translations.append([op[r][0] for r in range(3)])
    return SymOps(
        number=int(number or 0), hm=hm or "", hall_number=0, hall_symbol="",
        rotations=np.asarray(rotations, dtype=np.int64),
        translations=np.asarray(translations, dtype=np.float64))


def parse_site_model(path: str | Path) -> SiteModel:
    """从 CIF 读出**未展开**的不对称单位 + symop，建立站点模型。

    复用 ``cif.py`` 的 ``parse_symop`` / ``element_from_symbol`` /
    ``expand_symmetry``，保证与 P0 的对称展开口径一致。
    """
    p = Path(path)
    lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace")
             .splitlines() if not ln.lstrip().startswith("#")]

    cell = [1.0, 1.0, 1.0, 90.0, 90.0, 90.0]
    raw_atoms: list[tuple] = []
    symops: list = []
    formula: str | None = None
    hm: str | None = None
    number: int | None = None

    sym_tags = ("_symmetry_equiv_pos_as_xyz", "_space_group_symop_operation_xyz",
                "_symmetry_equiv_pos_as_xyz_", "_space_group_symop_xyz")

    i, in_loop, loop_tags = 0, False, []
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("_cell_length_a"):
            cell[0] = _to_float(s.split(None, 1)[1]) or cell[0]
        elif s.startswith("_cell_length_b"):
            cell[1] = _to_float(s.split(None, 1)[1]) or cell[1]
        elif s.startswith("_cell_length_c"):
            cell[2] = _to_float(s.split(None, 1)[1]) or cell[2]
        elif s.startswith("_cell_angle_alpha"):
            cell[3] = _to_float(s.split(None, 1)[1]) or cell[3]
        elif s.startswith("_cell_angle_beta"):
            cell[4] = _to_float(s.split(None, 1)[1]) or cell[4]
        elif s.startswith("_cell_angle_gamma"):
            cell[5] = _to_float(s.split(None, 1)[1]) or cell[5]
        elif s.startswith("_chemical_formula_sum"):
            parts = s.split(None, 1)
            if len(parts) > 1:
                formula = parts[1].strip().strip("'\"")
        elif s.startswith(("_symmetry_space_group_name_H-M",
                           "_space_group_name_H-M_alt")):
            parts = s.split(None, 1)
            if len(parts) > 1:
                hm = parts[1].strip().strip("'\"")
        elif s.startswith(("_symmetry_Int_Tables_number",
                           "_space_group_IT_number")):
            parts = s.split(None, 1)
            if len(parts) > 1:
                number = int(_to_float(parts[1]) or 0) or None
        elif s in ("loop_", "loop"):
            in_loop, loop_tags = True, []
            i += 1
            continue

        if in_loop:
            if s.startswith("_"):
                loop_tags.append(s)
                i += 1
                continue
            if s == "":
                in_loop = False
                i += 1
                continue
            cols = _split(s)
            rec = dict(zip(loop_tags, cols[:len(loop_tags)]))
            if any(t.startswith(k) for t in loop_tags for k in sym_tags):
                for t in loop_tags:
                    if t.startswith(sym_tags) and rec.get(t):
                        symops.append(parse_symop(rec[t]))
                i += 1
                continue
            if any(t.startswith("_atom_site") for t in loop_tags):
                x = _to_float(rec.get("_atom_site_fract_x"))
                y = _to_float(rec.get("_atom_site_fract_y"))
                z = _to_float(rec.get("_atom_site_fract_z"))
                if x is None or y is None or z is None:
                    i += 1
                    continue
                elem = (element_from_symbol(rec.get("_atom_site_type_symbol"))
                        or element_from_symbol(rec.get("_atom_site_label")))
                if elem is None:
                    i += 1
                    continue
                occ = _to_float(rec.get("_atom_site_occupancy")) or 1.0
                uiso = _to_float(rec.get("_atom_site_U_iso_or_equiv"))
                B = 8 * math.pi ** 2 * uiso if uiso is not None else 0.0
                raw_atoms.append((elem, x, y, z, occ, B))
                i += 1
                continue
            i += 1
            continue
        i += 1

    if not raw_atoms:
        raise ValueError(f"未能从 CIF 解析出原子位点: {p.name}")

    # 无 CIF 显式 symop 时用 spglib 生成（P1.1 能力）
    if not symops:
        from xinrefinement.core.symops import symops_from_spg
        ops = symops_from_spg(number=number, hm=hm)
        symops = ops.to_family_symops()
    ops_obj = family_to_symops(symops, number, hm)

    sites = []
    for (elem, x, y, z, occ, B) in raw_atoms:
        from xinrefinement.core.symops import free_coordinate_basis
        basis = free_coordinate_basis(ops_obj, (x, y, z))
        sites.append(Site(elem, (x, y, z), occ, B, basis, basis.shape[1]))

    return SiteModel(name=p.stem, cell=tuple(cell), sites=sites,
                     symops=symops, formula=formula, spacegroup=hm,
                     sg_number=number)


@dataclass(frozen=True)
class SiteRefineResult:
    """结构精修结果。"""

    params: tuple[float, ...]
    rwp: float
    success: bool
    history: tuple[float, ...]
    iters: int
    structures: tuple[CifStructure, ...]


def refine_sites(models: list[SiteModel], pat: Pattern, prm0: ProfileParams,
                 cfg, backend: str = "lm",
                 free_kinds: tuple[str, ...] = ("xyz", "B", "occ"),
                 occ_anchor: bool = True,
                 fixed_structures=()) -> SiteRefineResult:
    """独立结构精修（变量投影 + LM/scipy-trf）。

    ``free_kinds`` 可选 ``xyz`` / ``B`` / ``occ`` 的任意组合，便于 P1.3
    与 P1.4 分步验收；不启用的维度在向量里固定为 0。

    ``fixed_structures``（v1.4 #17）：多相体系里**不参与**结构精修的相。
    它们的计算谱作为常量基向量一并进入线性层，否则变量投影会把这些相的
    强度也算到被精修相的标度上，得到虚假的坐标位移。顺序不影响结果
    （线性层逐列求解），但必须与调用方后续重建相列表时的映射一致。

    **occ 锚定（``occ_anchor=True``，默认）**：单相里所有位点 occ 的绝对标度
    会被变量投影的线性层 scale 完全吸收（数学上不可辨识）——实测真值
    ``(Ti=0, O=+0.12)`` 与解 ``(Ti=-0.057, O=+0.056)`` 给出相同占位比、
    相同 Rwp。故每个物相**固定第一个位点的 occ 为基准**（标准 Rietveld 做法），
    只精修其余位点的相对占位。设 ``occ_anchor=False`` 可关闭（用于多相/
    含已知标度的场景，此时须自行处理简并）。
    """
    from xinrefinement.core.refine.nonlinear import RefineConfig

    if isinstance(cfg, RefineConfig):
        tmin, tmax = cfg.tmin, cfg.tmax
        n_bg, bg_mode = cfg.n_bg, cfg.bg_mode
        sigma, max_iter = cfg.sigma, cfg.max_iter
    else:
        tmin, tmax = getattr(cfg, "tmin", 5.0), getattr(cfg, "tmax", 90.0)
        n_bg, bg_mode = getattr(cfg, "n_bg", 3), getattr(cfg, "bg_mode", "cheb")
        sigma, max_iter = getattr(cfg, "sigma", None), getattr(cfg, "max_iter", 40)

    dims = [m.n_params for m in models]
    offsets = np.cumsum((0,) + tuple(dims)).tolist()
    tt, yo = pat.two_theta, pat.intensity
    sig = (np.sqrt(np.maximum(yo, 1.0)) if sigma is None
           else np.asarray(sigma, dtype=np.float64))
    history: list[float] = []

    fixed_rows = [compute_phase_profile(s, tt, prm0, tmin, tmax)
                  for s in fixed_structures]

    def residual_fn(x: np.ndarray) -> np.ndarray:
        structs = [m.to_structure(x[offsets[i]:offsets[i + 1]])
                   for i, m in enumerate(models)]
        rows = list(fixed_rows) + [
            compute_phase_profile(s, tt, prm0, tmin, tmax) for s in structs]
        basis = np.vstack(rows) if rows else np.zeros((0, tt.size))
        # v1.4 #17：手动/插值背景的固定锚点必须一并传入，否则结构精修
        # 用的是另一条背景曲线，坐标会被背景差吸收。
        bg_points = list(getattr(cfg, "bg_points", ()) or ()) or None
        _c, ycalc, _d = solve_linear_detail(basis, tt, yo, sig, n_bg, bg_mode,
                                            bg_points=bg_points)
        rwp = compute_rfactors(
            yo, ycalc, n_params=x.size + basis.shape[0] + n_bg).rwp
        history.append(rwp)
        return (yo - ycalc) / sig

    # 边界：按位点逐维生成（坐标系数 / dB / d_occ）
    lo, hi = [], []
    for m in models:
        for si, site in enumerate(m.sites):
            for _ in range(site.n_free):
                lo.append(XYZ_BOUNDS[0] if "xyz" in free_kinds else 0.0)
                hi.append(XYZ_BOUNDS[1] if "xyz" in free_kinds else 0.0)
            for kind, bd in (("B", B_BOUNDS), ("occ", OCC_BOUNDS)):
                anchored = (kind == "occ" and occ_anchor and si == 0)
                active = kind in free_kinds and not anchored
                lo.append(bd[0] if active else 0.0)
                hi.append(bd[1] if active else 0.0)
    n = sum(dims)
    x0 = np.zeros(n, dtype=np.float64)
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    # 固定维度（上下界同为 0）：LM 仍会把它当变量但不产生位移；
    # 用固定掩码一次性处理，避免先改 lo 再比较导致判断失效。
    fixed = np.isclose(lo, hi)
    lo[fixed] = 0.0
    hi[fixed] = 0.0

    if n == 0:
        residual_fn(x0)
        best_x, success = x0, True
    elif backend == "scipy":
        from scipy.optimize import least_squares
        # scipy 要求 lo < hi；固定维度用 ±eps
        lo2, hi2 = lo.copy(), hi.copy()
        fixed = lo == hi
        lo2[fixed] -= 1e-12
        hi2[fixed] += 1e-12
        sr = least_squares(residual_fn, x0, bounds=(lo2, hi2), method="trf",
                           x_scale="jac", max_nfev=3000)
        best_x, success = sr.x, bool(sr.success)
    else:
        lm = lm_minimize(residual_fn, x0, bounds=(lo, hi), max_iter=max_iter)
        best_x, success = lm.x, lm.success

    residual_fn(best_x)
    structs = tuple(m.to_structure(best_x[offsets[i]:offsets[i + 1]])
                    for i, m in enumerate(models))
    return SiteRefineResult(
        params=tuple(float(v) for v in best_x), rwp=float(history[-1]),
        success=bool(success), history=tuple(history), iters=len(history),
        structures=structs)
