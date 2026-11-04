"""位点识别与占位/O-z 精修（T3.1 · 新建，非 vendor）。

层状 α-NaFeO₂ 结构（R-3m #166）只有三个晶体学自由度值得精修：
- **Li 层位点占位** occ_Li（与该位点上 Ni 反位互补：occ_Li + occ_Ni = 1）
- **O 的 6c 参数 z_O**（层间氧位置，直接决定 (003)/(006)/(012) 强度比）

位点识别纪律（CIF_SOURCE.md 的 3a/3b 陷阱）
------------------------------------------
COD 1520789 采用**备用原点**：Li 层在 z=0、TM 层在 z=0.5（ITA 标准设定
正好相反）。因此位点绝不允许按 z 坐标或硬编码 Wyckoff 标签识别，只按
**位点内容**识别：Li 占比最大的金属簇 = Li 层位点。

簇的定义：R-3m 六方设定下 3a/3b 位点的三个等价位置相差 R 中心平移
(2/3,1/3,1/3) 或 (1/3,2/3,2/3)——坐标差（去整数后）等于 R 平移即同簇。
6c 的 O 站点含 ±z 两支，统一做 δ 平移即可（新 z_O 配置与逐支平移等价）。

精修策略（v1）
--------------
两段式：先用 `solve()` 把峰形/晶胞精修到位，再用本模块把 occ_Li/z_O 作为
**仅有的非线性参数**做第二段 LM（线性标度+背景每步解析求解，LM 自带
1e-4 中心差分雅可比，与 OCC_FD_STEP 口径一致）。占位与标度/背景强相关，
变量投影天然解耦这一相关性。
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from xinrefinement.core import constants as C
from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import compute_phase_profile
from xinrefinement.core.refine.lm import lm_minimize
from xinrefinement.core.refine.linear import solve_linear_detail
from xinrefinement.core.refine.rfactors import compute_rfactors

#: R 中心平移（六方设定，分数坐标）
_R_CENTERING = ((0.0, 0.0, 0.0), (2.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
                (1.0 / 3.0, 2.0 / 3.0, 2.0 / 3.0))
#: 过渡金属元素集合（反位/占位识别用；与 tools/build_cif_pack.py 同口径）
TM_ELEMS = {"Ni", "Co", "Mn", "Fe", "Al", "Cr", "V", "Ti", "Cu", "Zn"}
#: O 站点等价坐标的匹配容差（分数坐标）
_SITE_TOL = 1e-3
#: 结构变体盐值计数器（forward 峰缓存键的一部分，防 id 复用撞缓存）
_VARIANT = itertools.count(1)
#: 边界钳位容差：覆盖 LM 数值雅可比步长 1e-4（occ/z_O 的量级 <1 时步长即 1e-4）
_BOUND_SLACK = 1e-3


@dataclass(frozen=True)
class SiteModel:
    """一个 CifStructure 的位点分解结果（下标均指向 struct.atoms）。"""

    li_layer: tuple[int, ...]          # Li 层位点簇（含 Li 最多者）
    tm_layer: tuple[int, ...]          # TM 层位点簇
    o_site: tuple[int, ...]            # 全部 O 原子下标
    z_o: float                         # 当前 O 6c 参数（∈[0,0.5)，最接近 0.25 者）
    share: dict[int, float] = field(default_factory=dict)
    # share: Li 层簇内非 Li 原子的相对占据比例（约束 occ_Li + Σocc_其他 = 1）
    o_sign: dict[int, int] = field(default_factory=dict)
    # o_sign: O 原子的 6c 分支符号（+1: z ≡ +z_O+k/3；-1: z ≡ -z_O+k/3）。
    # z_O 平移必须分支定向：+z 分支移 +δ、-z 分支移 -δ。若全体统一平移，
    # O 的结构因子贡献变为 2·e^{2πilδ}·cos(2πl·z_O)，|F|² 中交叉项
    # cos(2πlδ) 为偶函数 -> δ 取正取负**伪简并**，精修会停在畸形结构上。


def _same_site(p1: tuple, p2: tuple) -> bool:
    """两分数坐标是否属同一 R-3m 位点（差 = 整数 + R 中心平移）。"""
    for r in _R_CENTERING:
        if all(abs((p1[k] - p2[k] - r[k]) - round(p1[k] - p2[k] - r[k]))
               < _SITE_TOL for k in range(3)):
            return True
    return False


def _cluster(idxs: list[int], atoms: list[tuple]) -> list[list[int]]:
    """把 (x,y,z) 相差 R 中心平移的原子归入同一簇（贪心，代表元比较）。"""
    clusters: list[list[int]] = []
    for i in idxs:
        for cl in clusters:
            if _same_site(atoms[i][1:4], atoms[cl[0]][1:4]):
                cl.append(i)
                break
        else:
            clusters.append([i])
    return clusters


def identify_sites(struct: CifStructure) -> SiteModel:
    """按内容识别层状位点点位（绝不按 z 坐标/标签 —— 见模块 docstring）。

    抛 ValueError：结构中无 Li 位点（明显非层状 NCA），或 O 不符合单一
    6c 参数模型（多独立 O 位点，z_O 平移模型不适用）。
    """
    atoms = struct.atoms
    o_idx = [i for i, a in enumerate(atoms) if a[0] == "O"]
    metal_idx = [i for i in range(len(atoms)) if i not in set(o_idx)]
    clusters = _cluster(metal_idx, atoms)

    li_total = lambda cl: sum(atoms[i][4] for i in cl if atoms[i][0] == "Li")
    li_clusters = [cl for cl in clusters if li_total(cl) > 1e-6]
    if not li_clusters:
        raise ValueError(f"{struct.name}: 未找到 Li 位点 —— 非层状 NCA 结构，"
                         "占位精修不适用")
    li_layer = max(li_clusters, key=li_total)
    others = [cl for cl in clusters if cl is not li_layer]
    tm_layer = max(others, key=lambda cl: sum(
        atoms[i][4] for i in cl if atoms[i][0] in TM_ELEMS)) if others else ()

    # Li 层簇内非 Li 原子的相对占比（互补约束用）。注意是**位点口径**：
    # 每个等价位置上 Σ元素 occ = 1，同簇内同元素的多原子分属不同等价
    # 位置，按原子求和再分摊会把 0.02 的反位错分摊成 0.02/3。
    non_li = [i for i in li_layer if atoms[i][0] != "Li"]
    elems: dict[str, float] = {}
    for i in non_li:
        elems.setdefault(atoms[i][0], atoms[i][4])
    tot = sum(elems.values())
    share = {i: (atoms[i][4] / tot if tot > 0 else 0.0) for i in non_li}

    # O 6c 参数：z∈[0,0.5) 中最接近 0.25 者；并验证全部 O 与 ±z+k/3 相容
    zs = sorted(atoms[i][3] % 1.0 for i in o_idx)
    if not zs:
        raise ValueError(f"{struct.name}: 结构中无 O 原子")
    z0 = min((z for z in zs if z < 0.5), key=lambda z: abs(z - 0.25),
             default=None)
    if z0 is None:
        z0 = min(zs, key=lambda z: min(abs(z - 0.25), abs(z - 0.75)))
    o_sign: dict[int, int] = {}
    for i in o_idx:                     # 按下标取值 —— zs 已排序，严禁 zip 错配
        z = atoms[i][3] % 1.0
        plus = any(abs(z - (z0 + k / 3.0) % 1.0) < _SITE_TOL
                   or abs(z - (z0 + k / 3.0) % 1.0 - 1.0) < _SITE_TOL
                   for k in range(3))
        minus = any(abs(z - (-z0 + k / 3.0) % 1.0) < _SITE_TOL
                    or abs(z - (-z0 + k / 3.0) % 1.0 - 1.0) < _SITE_TOL
                    for k in range(3))
        if not (plus or minus):
            raise ValueError(f"{struct.name}: O 位点不符合 6c 单一参数模型"
                             f"（z_O 平移精修不适用），z={z:.4f}")
        # 同时命中（z0≈1/6 等特殊值）时分支无差别，取 +1
        o_sign[i] = 1 if (plus or not minus) else -1
    return SiteModel(li_layer=tuple(li_layer), tm_layer=tuple(tm_layer),
                     o_site=tuple(o_idx), z_o=float(z0), share=share,
                     o_sign=o_sign)


def apply_occ_zo(struct: CifStructure, sites: SiteModel, occ_li: float,
                 z_o: float | None = None) -> CifStructure:
    """返回施加 occ_Li / z_O 后的**新** CifStructure（不改原结构）。

    - Li 层簇：Li 原子占位 -> occ_li；非 Li 原子按识别期 share 分配
      剩余 (1 − occ_li)（互补约束 occ_Li + occ_反位 = 1）。
    - O 原子：按 6c 分支定向平移——+z 分支 +δ、−z 分支 −δ（δ = z_o −
      sites.z_o）。统一平移会造成 δ ↔ −δ 伪简并（见 SiteModel.o_sign）。
    - 新结构带 _variant 盐值，保证 forward 峰缓存不因 id 复用而错配。
    """
    # 边界校验：显著越界拒绝（API 误用）；微小越界（LM 中心差分在边界处
    # 会探测 x±1e-4 的界外点）钳位 —— 否则雅可比评估直接崩掉精修。
    lo, hi = C.OCC_LI3A_BOUNDS
    if occ_li < lo - _BOUND_SLACK or occ_li > hi + _BOUND_SLACK:
        raise ValueError(f"occ_li={occ_li:.4f} 超出边界 {C.OCC_LI3A_BOUNDS}")
    occ_li = min(max(occ_li, lo), hi)
    if z_o is not None:
        zlo, zhi = C.Z_O_BOUNDS
        if z_o < zlo - _BOUND_SLACK or z_o > zhi + _BOUND_SLACK:
            raise ValueError(f"z_o={z_o:.4f} 超出边界 {C.Z_O_BOUNDS}")
        z_o = min(max(z_o, zlo), zhi)
    atoms = list(struct.atoms)
    if z_o is not None:
        d = z_o - sites.z_o
        for i in sites.o_site:
            e, x, y, z, occ, B = atoms[i]
            atoms[i] = (e, x, y, (z + sites.o_sign[i] * d) % 1.0, occ, B)
    for i in sites.li_layer:
        e, x, y, z, occ, B = atoms[i]
        if e == "Li":
            atoms[i] = (e, x, y, z, float(occ_li), B)
        else:
            atoms[i] = (e, x, y, z, (1.0 - occ_li) * sites.share[i], B)
    st = CifStructure(struct.name, struct.cell, atoms)
    st._variant = next(_VARIANT)          # noqa: SLF001 —— 有意公开的盐值位
    return st


@dataclass(frozen=True)
class OccRefineResult:
    """占位/O-z 第二段精修结果。"""

    occ_li: float
    z_o: float
    rf: object                            # RFactors
    ycalc: np.ndarray
    scales: np.ndarray
    bg: np.ndarray
    success: bool
    structure: CifStructure               # 施加最终 occ/z_O 的结构
    iters: int = 0
    history: list[float] = field(default_factory=list)


def refine_occ(phase: CifStructure, pat: Pattern, prm,
               sites: SiteModel | None = None,
               occ0: float = 0.98, zo0: float | None = None,
               refine_zo: bool = True, max_iter: int = 30,
               n_bg: int | None = None, bg_mode: str | None = None,
               tmin: float | None = None, tmax: float | None = None,
               ) -> OccRefineResult:
    """第二段精修：峰形/晶胞参数固定（prm），只调 occ_Li（与可选 z_O）。

    phase : 单相结构（v1 只支持单相；第二相槽位的联合精修属 P5）
    prm   : 第一段精修得到的 ProfileParams（不再变化）
    occ0/zo0 : 初值；zo0=None 时取识别到的当前值
    边界：occ_li ∈ OCC_LI3A_BOUNDS，z_o ∈ Z_O_BOUNDS（constants.py 唯一出处）。
    """
    sites = sites or identify_sites(phase)
    tt = pat.two_theta
    yo = pat.intensity
    sig = np.sqrt(np.maximum(yo, C.RFACTOR_SIGMA_FLOOR))
    n_bg = C.DEFAULT_N_BG if n_bg is None else n_bg
    bg_mode = C.DEFAULT_BG_MODE if bg_mode is None else bg_mode
    tmin = C.DEFAULT_TMIN if tmin is None else tmin
    tmax = C.DEFAULT_TMAX if tmax is None else tmax
    zo_start = sites.z_o if zo0 is None else float(zo0)
    history: list[float] = []

    def residual_fn(x: np.ndarray) -> np.ndarray:
        occ = float(x[0])
        zo = float(x[1]) if refine_zo else zo_start
        st = apply_occ_zo(phase, sites, occ, zo)
        row = compute_phase_profile(st, tt, prm, tmin, tmax)
        _c, ycalc, _d = solve_linear_detail(np.vstack([row]), tt, yo, sig,
                                            n_bg, bg_mode)
        rwp = compute_rfactors(yo, ycalc,
                               n_params=x.size + 1 + n_bg).rwp
        history.append(float(rwp))
        return (yo - ycalc) / sig

    lo_o, hi_o = C.OCC_LI3A_BOUNDS
    lo = [lo_o]
    hi = [hi_o]
    x0 = [float(np.clip(occ0, lo_o, hi_o))]
    if refine_zo:
        lo_z, hi_z = C.Z_O_BOUNDS
        lo.append(lo_z)
        hi.append(hi_z)
        x0.append(float(np.clip(zo_start, lo_z, hi_z)))
    lm = lm_minimize(residual_fn, np.array(x0),
                     bounds=(np.array(lo), np.array(hi)), max_iter=max_iter)
    occ = float(lm.x[0])
    zo = float(lm.x[1]) if refine_zo else zo_start
    st = apply_occ_zo(phase, sites, occ, zo)
    row = compute_phase_profile(st, tt, prm, tmin, tmax)
    coeffs, ycalc, _dropped = solve_linear_detail(np.vstack([row]), tt, yo,
                                                  sig, n_bg, bg_mode)
    n1 = row.shape[0]
    rf = compute_rfactors(yo, ycalc, n_params=lm.x.size + n1 + n_bg,
                          include_bg=C.RFACTOR_INCLUDE_BG)
    return OccRefineResult(occ_li=occ, z_o=zo, rf=rf, ycalc=ycalc,
                           scales=coeffs[:n1].copy(),
                           bg=coeffs[n1:].copy(), success=bool(lm.success),
                           structure=st, iters=lm.n_iter, history=history)
