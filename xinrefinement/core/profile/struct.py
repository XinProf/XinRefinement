# vendored from PolyXRD-RutAna :: rutana/core/profile/struct.py
"""vendor: 倒易基矢与结构因子计算（T3.2）。

Vendored from PolyXRD-SynthPattern xrd_synth_engine.py — © 2026 PolyXRD Team,
dual-licensed (Academic/Commercial)，家族内复用。
复制范围: reciprocal_basis / compute_peaks（原样，含 po 择优取向与 wavelengths 参数）。
完整倒易点枚举自动包含多重性，|F|² 在全晶胞原子集合上计算。
"""
from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

from xinrefinement.core.profile.cif import ATOMIC_SCATTERING, ATOMIC_Z, CifStructure
from xinrefinement.core.profile.shape import march_dollase_weight

# 峰位合并容差(度)
TWO_THETA_TOL = 1e-3
# 与 SynthPattern v1.2.1 一致的缺省扫描窗口
DEFAULT_TWO_MIN = 10.0
DEFAULT_TWO_MAX = 90.0

#: 一次性向量化枚举的倒易点上限。超过它（超大晶胞，H>~110）退回逐点循环，
#: 保证内存不爆——那时 (2H+1)³ 已过亿，向量化的 meshgrid 本身就撑不住。
_MAX_ENUM = 4_000_000


def reciprocal_basis(a: float, b: float, c: float,
                     al: float, be: float, ga: float):
    """由晶胞参数计算倒易基矢 (a*, b*, c*)，单位 1/Å。"""
    al = math.radians(al); be = math.radians(be); ga = math.radians(ga)
    va = np.array([a, 0.0, 0.0])
    vb = np.array([b * math.cos(ga), b * math.sin(ga), 0.0])
    cx = c * math.cos(be)
    cy = c * (math.cos(al) - math.cos(be) * math.cos(ga)) / math.sin(ga)
    cz = c * math.sqrt(max(0.0,
        1 - math.cos(al) ** 2 - math.cos(be) ** 2 - math.cos(ga) ** 2
        + 2 * math.cos(al) * math.cos(be) * math.cos(ga))) / math.sin(ga)
    vc = np.array([cx, cy, cz])
    V = float(np.dot(va, np.cross(vb, vc)))
    a_star = np.cross(vb, vc) / V
    b_star = np.cross(vc, va) / V
    c_star = np.cross(va, vb) / V
    return a_star, b_star, c_star


def compute_peaks(struct: CifStructure,
                  wavelength: float = 1.5406,
                  two_min: float = DEFAULT_TWO_MIN,
                  two_max: float = DEFAULT_TWO_MAX,
                  po=None, wavelengths=None,
                  po_detail: bool = False, with_dirs: bool = False):
    """返回 (list[(two_theta, |F|²·LP, d)], skipped_elements)；
    ``po_detail=True`` 时返回 ``(peaks, skipped, detail)``。

    wavelengths: resolve_wavelengths() 的结果。None -> 单色光。
    po: (h, k, l, r) 择优取向 —— (hkl) 为择优面法向, r 为 March–Dollase 参数。
    完整倒易点枚举 -> 强度求和即自动包含多重性。
    with_dirs: True 时每峰多带一个元素——该反射的**笛卡尔单位方向**
        ``(nx, ny, nz)``（倒易矢量方向，即晶面法向），供各向异性尺寸/
        应变（Popa LB）按晶向取值使用。合并峰取首个 hkl 的方向。
    po_detail: True 时额外返回与 peaks 逐项对齐的贡献明细
        ``detail[i] = [(val_pre_po, cos_alpha), ...]``，其中 val_pre_po 为
        未乘 PO 权重的 |F|²·LP·wgt，cos_alpha 为该 hkl 与择优面法向的夹角
        余弦。精修可据此在任意 r 下廉价重算峰强（前向施加 PO，无需重算峰
        列表，数值与直接传 po=(h,k,l,r) 完全一致）。po_detail=True 时
        po 不能为 None（否则抛 ValueError）；po_detail=False 时行为与
        既往版本逐位一致。
    """
    if po_detail and po is None:
        raise ValueError("po_detail=True 时 po 不能为 None")
    a, b, c, al, be, ga = struct.cell
    ast, bst, cst = reciprocal_basis(a, b, c, al, be, ga)

    # 预计算每原子的散射参数
    zs, a1, a2, a3, a4, b1, b2, b3, b4 = [], [], [], [], [], [], [], [], []
    xs, ys, zs_, occs, Bs = [], [], [], [], []
    skipped = []
    for (elem, x, y, z, occ, B) in struct.atoms:
        coeff = ATOMIC_SCATTERING.get(elem)
        if coeff is None or elem not in ATOMIC_Z:
            skipped.append(elem)
            continue
        Z = ATOMIC_Z[elem]
        zs.append(Z)
        # 展开 4 项 Gaussian 系数
        a1.append(coeff[0][0]); a2.append(coeff[1][0])
        a3.append(coeff[2][0]); a4.append(coeff[3][0])
        b1.append(coeff[0][1]); b2.append(coeff[1][1])
        b3.append(coeff[2][1]); b4.append(coeff[3][1])
        xs.append(x); ys.append(y); zs_.append(z)
        occs.append(occ); Bs.append(B)
    if not zs:
        raise ValueError(f"无可用散射因子: {struct.name} (跳过 {skipped})")

    Z = np.array(zs, float)
    A = np.array([a1, a2, a3, a4], float)        # shape (4, natom)
    Bc = np.array([b1, b2, b3, b4], float)
    X = np.array([xs, ys, zs_], float)           # (3, natom)
    OCC = np.array(occs, float)
    BW = np.array(Bs, float)
    # 相消干涉的反射理论上 |F|²=0, 浮点残差约 1e-32 相对量级。
    # 按 s=0 处的最大可能 |F|² 设相对阈值滤掉"数值噪声峰"。
    f_ref_sq = float(np.sum(Z * OCC)) ** 2
    tol_i = max(f_ref_sq * 1e-9, 1e-300)

    comps = wavelengths if wavelengths is not None else [(float(wavelength), 1.0)]
    max_g = 2 * math.sin(math.radians(two_max / 2)) / min(w for w, _ in comps)
    min_g = 2 * math.sin(math.radians(two_min / 2)) / max(w for w, _ in comps)
    min_recip = min(np.linalg.norm(ast), np.linalg.norm(bst), np.linalg.norm(cst))
    H = int(math.ceil(max_g / min_recip)) + 2
    H = max(H, 6)

    # 择优取向方向 (笛卡尔单位矢量; hkl 的法向即其倒易矢量)
    po_vec, po_r, po_neutral = None, 1.0, True
    if po is not None:
        ph, pk, pl, po_r = po
        po_r = float(po_r)
        if po_r <= 0:
            raise ValueError("March–Dollase r 必须 > 0")
        _v = int(ph) * ast + int(pk) * bst + int(pl) * cst
        _nv = float(np.linalg.norm(_v))
        if _nv <= 0:
            raise ValueError("择优取向面指数 (h k l) 无效")
        po_vec = _v / _nv
        po_neutral = abs(po_r - 1.0) < 1e-12

    ctx = _PeakCtx(H=H, ast=ast, bst=bst, cst=cst, Z=Z, A=A, Bc=Bc, X=X,
                   OCC=OCC, BW=BW, tol_i=tol_i, comps=comps,
                   min_g=min_g, max_g=max_g,
                   two_min=float(two_min), two_max=float(two_max),
                   po_vec=po_vec, po_r=po_r, po_neutral=po_neutral,
                   po_detail=bool(po_detail), with_dirs=bool(with_dirs))
    if (2 * H + 1) ** 3 <= _MAX_ENUM:
        out, detail = _enumerate_vec(ctx)
    else:                                        # 超大晶胞：逐点循环兜底
        out, detail = _enumerate_loop(ctx)
    if po_detail:
        return out, skipped, detail
    return out, skipped


class _PeakCtx(NamedTuple):
    """``compute_peaks`` 预处理后的只读上下文（供两个枚举内核共用）。

    拆出来的目的：让「逐点循环」与「向量化」两套实现在**完全相同的输入**
    上跑，便于用前者当后者的参照做数值回归；同时避免把十几个参数在三个
    函数间来回传。
    """

    H: int
    ast: np.ndarray
    bst: np.ndarray
    cst: np.ndarray
    Z: np.ndarray
    A: np.ndarray
    Bc: np.ndarray
    X: np.ndarray
    OCC: np.ndarray
    BW: np.ndarray
    tol_i: float
    comps: list
    min_g: float
    max_g: float
    two_min: float
    two_max: float
    po_vec: object
    po_r: float
    po_neutral: bool
    po_detail: bool
    with_dirs: bool


def _enumerate_vec(ctx: _PeakCtx):
    """向量化倒易点枚举（v1.5 性能修复，2026-11-07）。

    旧实现是 ``for h: for k: for l:`` 的三重 Python 循环，对每个 hkl 做一次
    小 numpy 运算——IUCr 纯刚玉（H=19 → 59319 次迭代、只有约 2100 个落在
    窗口内）单次耗时 **443 ms**，占一次残差评估总耗时的 86%（cProfile 实测
    18.1 s / 21.0 s），而残差评估又是 LM 里调用最频繁的一环。改成先
    ``meshgrid`` 出全部 (h,k,l) 再整体筛 g、整体算 |F|²、整体按 Kα 分量
    展开、整体按 1e-3° 合并后，同一份数据降到毫秒量级。

    语义与 ``_enumerate_loop`` 逐项对齐（枚举顺序 h→k→l、g 判界的 ±1e-9
    松弛、``i_hkl <= tol_i`` 剔除、``wpo <= 0`` / ``val <= 0`` 剔除、
    合并键 ``round(2θ/1e-3)`` 取**首次出现**的 2θ/d/方向、detail 按出现
    顺序累积）。浮点求和顺序也保持一致（``np.add.reduceat`` 作用在
    stable-sorted 数组上 = 按出现顺序累加）。
    """
    H = ctx.H
    n = np.arange(-H, H + 1, dtype=np.int64)
    hh, kk, ll = np.meshgrid(n, n, n, indexing="ij")
    hh = hh.ravel(); kk = kk.ravel(); ll = ll.ravel()
    live = (hh != 0) | (kk != 0) | (ll != 0)
    if not live.all():
        hh = hh[live]; kk = kk[live]; ll = ll[live]

    R = (np.multiply.outer(hh, ctx.ast) + np.multiply.outer(kk, ctx.bst)
         + np.multiply.outer(ll, ctx.cst))          # (N, 3) 倒易矢量
    g = np.sqrt(R[:, 0] * R[:, 0] + R[:, 1] * R[:, 1] + R[:, 2] * R[:, 2])
    sel = (g >= ctx.min_g - 1e-9) & (g <= ctx.max_g + 1e-9)
    if not sel.any():
        return ([], []) if ctx.po_detail else ([], None)
    if not sel.all():
        hh = hh[sel]; kk = kk[sel]; ll = ll[sel]; R = R[sel]; g = g[sel]

    s2 = (g / 2.0) ** 2
    # f_j = Z_j - 41.78214*s2 * Σ_i a_i exp(-b_i s2)
    acc = np.zeros((g.size, ctx.Z.size))
    for i in range(4):
        acc += ctx.A[i] * np.exp(-ctx.Bc[i] * s2[:, None])
    fs = ctx.Z - 41.78214 * s2[:, None] * acc
    # F = Σ f·occ·exp(2πi h·r)·exp(-B s2)
    gdr = (hh[:, None] * ctx.X[0] + kk[:, None] * ctx.X[1]
           + ll[:, None] * ctx.X[2])
    F = np.sum(fs * ctx.OCC * np.exp(2j * math.pi * gdr)
               * np.exp(-ctx.BW * s2[:, None]), axis=1)
    i_hkl = F.real ** 2 + F.imag ** 2
    ok = i_hkl > ctx.tol_i

    wpo = np.ones(g.size)
    ca = np.zeros(g.size)
    if ctx.po_vec is not None and (not ctx.po_neutral or ctx.po_detail):
        ca = (R @ ctx.po_vec) / g
        if not ctx.po_neutral:
            c2 = np.clip(ca * ca, 0.0, 1.0)
            r = ctx.po_r
            wpo = (r * r * c2 + (1.0 - c2) / r) ** -1.5
            ok = ok & (wpo > 0)
    if not ok.any():
        return ([], []) if ctx.po_detail else ([], None)

    wls = np.array([w for w, _ in ctx.comps], float)
    wgts = np.array([wgt for _, wgt in ctx.comps], float)
    with np.errstate(divide="ignore", invalid="ignore"):
        s_arg = wls[None, :] * g[:, None] / 2.0
        theta = np.arcsin(np.clip(s_arg, -1.0, 1.0))
        tt = np.degrees(2.0 * theta)
        good = ok[:, None] & (s_arg < 1.0)
        good = good & (tt >= ctx.two_min - 1e-9) & (tt <= ctx.two_max + 1e-9)
        ct = np.cos(2.0 * theta)
        lp = (1.0 + ct * ct) / (np.sin(theta) ** 2 * np.cos(theta))
        val0 = i_hkl[:, None] * lp * wgts[None, :]
        val = val0 * wpo[:, None]
        good = good & (val > 0)
    if not good.any():
        return ([], []) if ctx.po_detail else ([], None)

    # ravel 走 C 序 = 「先 hkl、后 Kα 分量」，与旧循环的追加顺序一致
    m = good.ravel()
    keys = np.rint(tt.ravel()[m] / TWO_THETA_TOL).astype(np.int64)
    vals_f = val.ravel()[m]
    tt_f = tt.ravel()[m]
    row_f = np.repeat(np.arange(g.size), wls.size)[m]
    order = np.argsort(keys, kind="stable")
    ksort = keys[order]
    starts = np.r_[0, np.flatnonzero(np.diff(ksort)) + 1]
    sums = np.add.reduceat(vals_f[order], starts)
    rep = order[starts]                      # 每个合并键的首次出现
    pos = tt_f[rep]
    d_sp = 1.0 / g
    dvals = d_sp[row_f[rep]]

    srt = np.argsort(pos, kind="stable")
    out: list = []
    detail_lists: list = []
    if ctx.po_detail:
        v0_f = val0.ravel()[m][order]
        ca_f = ca[row_f][order]
        bounds = np.r_[starts, ksort.size]
        groups = [list(zip(v0_f[s:e].tolist(), ca_f[s:e].tolist()))
                  for s, e in zip(bounds[:-1], bounds[1:])]
    for j in srt:
        if sums[j] <= 0:
            continue
        item = (float(pos[j]), float(sums[j]), float(dvals[j]))
        if ctx.with_dirs:
            k = row_f[rep[j]]
            item += ((float(R[k, 0] / g[k]), float(R[k, 1] / g[k]),
                      float(R[k, 2] / g[k])),)
        out.append(item)
        if ctx.po_detail:
            detail_lists.append(groups[j])
    if ctx.po_detail:
        return out, detail_lists
    return out, None


def _enumerate_loop(ctx: _PeakCtx):
    """逐点循环枚举（原始实现，保留作超大晶胞兜底与向量化版的数值参照）。"""
    peaks: dict[int, list] = {}
    detail: dict[int, list] = {}
    dirs: dict[int, tuple] = {}
    ast, bst, cst = ctx.ast, ctx.bst, ctx.cst
    for h in range(-ctx.H, ctx.H + 1):
        for k in range(-ctx.H, ctx.H + 1):
            for l in range(-ctx.H, ctx.H + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                rlv = h * ast + k * bst + l * cst
                g = math.sqrt(float(rlv @ rlv))
                if g < ctx.min_g - 1e-9 or g > ctx.max_g + 1e-9:
                    continue
                s2 = (g / 2.0) ** 2
                fs = ctx.Z - 41.78214 * s2 * np.sum(
                    ctx.A * np.exp(-ctx.Bc * s2), axis=0)
                g_dot_r = h * ctx.X[0] + k * ctx.X[1] + l * ctx.X[2]
                phase = np.exp(2j * math.pi * g_dot_r) * np.exp(-ctx.BW * s2)
                F = np.sum(fs * ctx.OCC * phase)
                i_hkl = (F.real ** 2 + F.imag ** 2)
                if i_hkl <= ctx.tol_i:
                    continue
                wpo = 1.0
                ca = 0.0
                if ctx.po_vec is not None and (not ctx.po_neutral
                                               or ctx.po_detail):
                    ca = float(rlv @ ctx.po_vec) / g
                    if not ctx.po_neutral:
                        wpo = march_dollase_weight(ca, ctx.po_r)
                        if wpo <= 0:
                            continue
                for wl, wgt in ctx.comps:
                    s_arg = wl * g / 2
                    if s_arg >= 1.0:
                        continue
                    theta = math.asin(s_arg)
                    two_theta = math.degrees(2 * theta)
                    if (two_theta < ctx.two_min - 1e-9
                            or two_theta > ctx.two_max + 1e-9):
                        continue
                    lp = ((1 + math.cos(2 * theta) ** 2)
                          / (math.sin(theta) ** 2 * math.cos(theta)))
                    val0 = i_hkl * lp * wgt
                    val = val0 * wpo
                    if val <= 0:
                        continue
                    key = round(two_theta / TWO_THETA_TOL)
                    if key in peaks:
                        peaks[key][0] += val
                    else:
                        peaks[key] = [val, two_theta, 1.0 / g]
                        if ctx.with_dirs:
                            dirs[key] = (float(rlv[0] / g), float(rlv[1] / g),
                                         float(rlv[2] / g))
                    if ctx.po_detail:
                        detail.setdefault(key, []).append((val0, ca))

    combined = []
    for key, v in peaks.items():
        if v[0] <= 0:
            continue
        combined.append((v[1], v[0], v[2],
                         detail.get(key, []) if ctx.po_detail else None))
    combined.sort(key=lambda t: t[0])
    if ctx.po_detail:
        out = []
        for p, i, d, _det in combined:
            item = (p, i, d)
            if ctx.with_dirs:
                item = item + (dirs.get(round(p / TWO_THETA_TOL),
                                        (0.0, 0.0, 1.0)),)
            out.append(item)
        return out, [det for _p, _i, _d, det in combined]
    out = []
    for p, i, d, _det in combined:
        item = (p, i, d)
        if ctx.with_dirs:
            item = item + (dirs.get(round(p / TWO_THETA_TOL),
                                    (0.0, 0.0, 1.0)),)
        out.append(item)
    return out, None
