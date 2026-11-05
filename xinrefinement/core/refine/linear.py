# vendored from PolyXRD-RutAna :: rutana/core/refine/linear.py
"""B 法精修 · 线性层（T4.1）：相标度 S_p + Chebyshev 背景。

设计矩阵 A = [P_1 ... P_P | b_0 ... b_{n_bg-1}]，用 scipy.linalg.lstsq 求解。
负标度约束：解完后若某 S_p < 0，把该相移出设计矩阵重解一轮；
重解后仍为负则该相 scale 置 0 并标记 phase_dropped（被剔除相同样记入）。
"""
from __future__ import annotations

import numpy as np
import scipy.linalg


def chebyshev_basis(two_theta: np.ndarray, n_terms: int) -> np.ndarray:
    """Chebyshev 背景基，shape (N, n_terms)，x 已映射到 [-1, 1]。

    递推: T_0 = 1, T_1 = x, T_{n+1} = 2x·T_n − T_{n−1}。
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    lo, hi = float(tt[0]), float(tt[-1])
    if hi <= lo:
        raise ValueError("two_theta 区间宽度必须 > 0")
    x = 2.0 * (tt - lo) / (hi - lo) - 1.0
    basis = np.empty((tt.size, int(n_terms)), dtype=np.float64)
    basis[:, 0] = 1.0
    if n_terms > 1:
        basis[:, 1] = x
    for j in range(2, n_terms):
        basis[:, j] = 2.0 * x * basis[:, j - 1] - basis[:, j - 2]
    return basis


def tent_basis(two_theta: np.ndarray, n_nodes: int) -> np.ndarray:
    """tent（分片线性帽函数）背景基，shape (N, n_nodes)。

    在 [lo, hi] 上均匀布 n_nodes 个节点，第 j 列是以第 j 个节点为顶点的
    三角帽函数。相比 Chebyshev 更贴合真实粉末谱的大弯背景（v1.0.0 实证，
    见 docs/VALIDATION_v1.0.0.md B 法章节：20–120° 实测谱 Rwp 10.6%→9.5%）。
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    lo, hi = float(tt[0]), float(tt[-1])
    if hi <= lo:
        raise ValueError("two_theta 区间宽度必须 > 0")
    n = max(int(n_nodes), 2)
    nodes = np.linspace(lo, hi, n)
    basis = np.zeros((tt.size, n), dtype=np.float64)
    for j in range(n):
        if j > 0:
            m = (tt >= nodes[j - 1]) & (tt <= nodes[j])
            basis[m, j] = (tt[m] - nodes[j - 1]) / (nodes[j] - nodes[j - 1])
        if j < n - 1:
            m = (tt >= nodes[j]) & (tt <= nodes[j + 1])
            basis[m, j] = (nodes[j + 1] - tt[m]) / (nodes[j + 1] - nodes[j])
    return basis


def interp_background_nodes(two_theta: np.ndarray, intensity: np.ndarray,
                            n_nodes: int, iterations: int = 10
                            ) -> list[tuple[float, float]]:
    """v1.2.0 插值背景提取（借鉴 MAUD ``backgroundSubtraction`` 语义）。

    MAUD 默认「10 次迭代 × 每 150 点一个插值段」的**固定**插值背景，
    与多项式层可加。这里实现同族算法：

    1. 在 [lo, hi] 均匀布 ``n_nodes`` 个锚点，初始值取段内最低强度；
    2. 每轮：线性插值成曲线 → 只保留「贴着背景」的观测点
       （``y ≤ 背景 + 2√背景``，计数统计 2σ 带，自动避开衍射峰）→
       锚点更新为所在段贴背景点的**中位数**（合成谱实测 p50 误差
       < 1 counts，20% 分位会系统性低偏 ~30 counts）；
    3. ``iterations`` 轮后返回锚点序列（2θ 递增）。

    返回点列可直接喂给 :func:`manual_basis`（固定曲线、不参与 LS），
    因此 ``bg_mode="interp"`` 在引擎层被归一化为 manual 分支（见
    ``solve.py``），免费获得「从 y_obs 扣除固定背景」的既有路径。
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    yo = np.asarray(intensity, dtype=np.float64)
    if tt.size != yo.size or tt.size == 0:
        raise ValueError("two_theta / intensity 必须等长且非空")
    n = max(int(n_nodes), 2)
    nodes = np.linspace(float(tt[0]), float(tt[-1]), n)
    seg_id = np.clip(np.searchsorted(nodes, tt, side="right") - 1, 0, n - 2)

    vals = np.empty(n, dtype=np.float64)
    vals[0] = yo[seg_id == 0].min()
    vals[-1] = yo[seg_id == n - 2].min()
    for j in range(1, n - 1):
        m = seg_id == j
        vals[j] = yo[m].min() if m.any() else max(vals[j - 1], 0.0)
    vals = np.maximum(vals, 0.0)

    for _ in range(max(int(iterations), 1)):
        bkg = np.interp(tt, nodes, vals)
        noise = np.sqrt(np.maximum(bkg, 1.0))
        near = yo <= bkg + 2.0 * noise
        for j in range(n):
            lo_b = nodes[max(j - 1, 0)]
            hi_b = nodes[min(j + 1, n - 1)]
            m = near & (tt >= lo_b) & (tt <= hi_b)
            if not m.any():
                m = (tt >= lo_b) & (tt <= hi_b)
            if m.any():
                vals[j] = float(np.percentile(yo[m], 50.0))
        vals = np.maximum(vals, 0.0)
    return [(float(x), float(v)) for x, v in zip(nodes, vals)]


def adaptive_n_bg(tmin: float, tmax: float, degree_span: float = 6.0,
                  lo: int = 6, hi: int = 30) -> int:
    """v1.2.0 P1：tent/interp 背景的自适应节点数 ≈ 1 节点 / ``degree_span`` 度。

    实样对拍（docs/评估报告-实样对拍-MAUD-v1.md §4.3/§11.2）实证：固定
    ``n_bg=3`` 的 cheb 对「低角陡降 + 荧光本底」谱严重不足（7 样均值差
    ~4 点），tent14（5–90°）把均值从 23.06% 拉到 18.84%。MAUD 侧等效
    自由度（Chebyshev7 + 10 次插值迭代 × 150 点间隔）同量级。
    """
    span = abs(float(tmax) - float(tmin))
    if span <= 0.0:
        return lo
    return int(min(hi, max(lo, round(span / degree_span))))


def manual_basis(two_theta: np.ndarray,
                 points: list[tuple[float, float]] | tuple) -> np.ndarray:
    """P2.2 手动插值点背景基：用户放置的 (2θ, 强度) 点之间线性插值。

    返回 shape ``(N, 1)`` 的**固定背景曲线**（不再作为线性参数求解），
    由 solve_linear_detail 把它当作已知背景从 y_obs 中扣除。这样齿轮弹窗里
    拖拽的背景点与 cheb/tent 的「可精修系数」是两种正交的工作方式。

    ``points`` 需 ≥2 个且 2θ 严格递增；区间外按端点值常值外推。
    """
    tt = np.asarray(two_theta, dtype=np.float64)
    pts = sorted(((float(x), float(y)) for x, y in points), key=lambda t: t[0])
    if len(pts) < 2:
        raise ValueError("手动背景至少需要 2 个点")
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    if np.any(np.diff(xs) <= 0):
        raise ValueError("手动背景点的 2θ 必须严格递增")
    return np.interp(tt, xs, ys).reshape(-1, 1)


def background_basis(two_theta: np.ndarray, n_terms: int,
                     mode: str = "cheb",
                     points: list[tuple[float, float]] | None = None) -> np.ndarray:
    """背景基统一入口：``cheb`` / ``tent`` / ``manual``（P2.2）。

    ``manual`` 需给 ``points``；返回固定背景曲线 (N,1)，其系数恒为 1，
    由调用方作为已知背景扣除（见 :func:`solve_linear_detail` 的 manual 分支）。
    """
    if mode == "cheb":
        return chebyshev_basis(two_theta, n_terms)
    if mode == "tent":
        return tent_basis(two_theta, n_terms)
    if mode == "manual":
        if not points:
            raise ValueError("manual 背景模式需要提供背景插值点 points")
        return manual_basis(two_theta, points)
    raise ValueError(f"未知背景模式: {mode}（可选 cheb / tent / manual）")


def _solve(A: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """加权 lstsq：min || w·(A c − y) ||₂。"""
    coeffs, *_ = scipy.linalg.lstsq(A * w[:, None], y * w)
    return coeffs


def solve_linear_detail(basis_phases: np.ndarray, grid: np.ndarray,
                        yobs: np.ndarray, sigma: np.ndarray | None,
                        n_bg: int = 3, bg_mode: str = "cheb",
                        bg_points: list[tuple[float, float]] | None = None
                        ) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """线性求解（完整版，带负标度剔除）。

    basis_phases: shape (P, N) 各相 profile（单相允许 (N,)）
    bg_mode     : "cheb"（默认）/ "tent" / "manual"（P2.2，需 bg_points）/
                  "interp"（v1.2.0，需 bg_points —— MAUD 两层可加语义：
                  自动提取的**固定**插值曲线 + 其上自由 Chebyshev ``n_bg`` 项）
    返回 (coeffs, ycalc, dropped)：
      coeffs = [S_1..S_P, b_0..b_{n_bg-1}]（相位在前，背景在后）
      dropped: scale 被置 0 的相下标（剔除重解 + 重解后仍为负的相）

    P2.2 ``manual`` 分支：用户放置的背景点是**固定曲线**（非可解系数），
    先从 y_obs 扣除再解 scale，返回 coeffs 里背景位恒为 [1.0] 作占位；
    ycalc 已包含该背景。cheb/tent 路径逐位不变（golden 保护）。
    """
    bp = np.atleast_2d(np.asarray(basis_phases, dtype=np.float64))
    y = np.asarray(yobs, dtype=np.float64)
    g = np.asarray(grid, dtype=np.float64)
    n_phase = bp.shape[0]
    n_bg = int(n_bg)

    if bg_mode == "manual":
        fixed_bg = manual_basis(g, bg_points or []).ravel()
        w_m = np.ones_like(y) if sigma is None else 1.0 / np.asarray(sigma, float)
        y_res = y - fixed_bg
        sol = _solve(bp.T, y_res, w_m)
        scales = np.where(sol < 0.0, 0.0, sol)
        dropped = [int(i) for i in np.flatnonzero(sol < 0.0)]
        coeffs = np.concatenate([scales, np.ones(1)])
        ycalc = bp.T @ scales + fixed_bg
        return coeffs, ycalc, dropped

    if bg_mode == "interp":
        if not bg_points:
            raise ValueError("interp 背景模式需要 bg_points"
                             "（由 solve()/refine_cell_full 一次性提取）")
        offset = manual_basis(g, list(bg_points)).ravel()
        bg = chebyshev_basis(g, n_bg)
    elif bg_mode == "tent":
        offset = np.zeros_like(y)
        bg = tent_basis(g, n_bg)
    elif bg_mode == "cheb":
        offset = np.zeros_like(y)
        bg = chebyshev_basis(g, n_bg)
    else:
        raise ValueError(f"未知背景模式: {bg_mode}（可选 cheb / tent / "
                         f"manual / interp）")

    w = np.ones_like(y) if sigma is None else 1.0 / np.asarray(sigma, float)
    y_work = y - offset          # interp：固定层先扣，可解层在其上拟合

    scales = np.zeros(n_phase)
    keep = list(range(n_phase))
    bg_c = np.zeros(n_bg)
    dropped: list[int] = []

    for attempt in range(2):
        if keep:
            A = np.hstack([bp[keep].T, bg])
            sol = _solve(A, y_work, w)
            for j, idx in enumerate(keep):
                scales[idx] = sol[j]
            bg_c = sol[len(keep):]
        else:
            bg_c = _solve(bg, y_work, w)
        neg = [idx for idx in keep if scales[idx] < 0.0]
        if not neg:
            break
        if attempt == 1:
            # 重解一轮后仍为负 -> 置 0 并标记 phase_dropped
            dropped = list(neg)
            for idx in neg:
                scales[idx] = 0.0
            break
        # 第一轮有负标度：剔除这些相（scale 置 0），重解一轮
        dropped = list(neg)
        for idx in neg:
            scales[idx] = 0.0
        keep = [idx for idx in range(n_phase) if idx not in dropped]

    coeffs = np.concatenate([scales, bg_c])
    ycalc = np.hstack([bp.T, bg]) @ coeffs + offset
    return coeffs, ycalc, dropped


def solve_linear(basis_phases: np.ndarray, grid: np.ndarray, yobs: np.ndarray,
                 sigma: np.ndarray | None, n_bg: int = 3,
                 bg_mode: str = "cheb",
                 bg_points: list[tuple[float, float]] | None = None
                 ) -> tuple[np.ndarray, np.ndarray]:
    """契约版入口：返回 (coeffs, ycalc)，coeffs = [S_1..S_P, b_0..b_{n_bg-1}]。"""
    coeffs, ycalc, _dropped = solve_linear_detail(
        basis_phases, grid, yobs, sigma, n_bg, bg_mode, bg_points)
    return coeffs, ycalc
