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


def background_basis(two_theta: np.ndarray, n_terms: int,
                     mode: str = "cheb") -> np.ndarray:
    """背景基统一入口：mode="cheb"（默认）或 "tent"。"""
    if mode == "cheb":
        return chebyshev_basis(two_theta, n_terms)
    if mode == "tent":
        return tent_basis(two_theta, n_terms)
    raise ValueError(f"未知背景模式: {mode}（可选 cheb / tent）")


def _solve(A: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """加权 lstsq：min || w·(A c − y) ||₂。"""
    coeffs, *_ = scipy.linalg.lstsq(A * w[:, None], y * w)
    return coeffs


def solve_linear_detail(basis_phases: np.ndarray, grid: np.ndarray,
                        yobs: np.ndarray, sigma: np.ndarray | None,
                        n_bg: int = 3, bg_mode: str = "cheb"
                        ) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """线性求解（完整版，带负标度剔除）。

    basis_phases: shape (P, N) 各相 profile（单相允许 (N,)）
    bg_mode     : "cheb"（默认）或 "tent"（真实数据推荐，n_bg=节点数）
    返回 (coeffs, ycalc, dropped)：
      coeffs = [S_1..S_P, b_0..b_{n_bg-1}]（相位在前，背景在后）
      dropped: scale 被置 0 的相下标（剔除重解 + 重解后仍为负的相）
    """
    bp = np.atleast_2d(np.asarray(basis_phases, dtype=np.float64))
    y = np.asarray(yobs, dtype=np.float64)
    g = np.asarray(grid, dtype=np.float64)
    n_phase = bp.shape[0]
    n_bg = int(n_bg)
    bg = background_basis(g, n_bg, bg_mode)
    w = np.ones_like(y) if sigma is None else 1.0 / np.asarray(sigma, float)

    scales = np.zeros(n_phase)
    keep = list(range(n_phase))
    bg_c = np.zeros(n_bg)
    dropped: list[int] = []

    for attempt in range(2):
        if keep:
            A = np.hstack([bp[keep].T, bg])
            sol = _solve(A, y, w)
            for j, idx in enumerate(keep):
                scales[idx] = sol[j]
            bg_c = sol[len(keep):]
        else:
            bg_c = _solve(bg, y, w)
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
    ycalc = np.hstack([bp.T, bg]) @ coeffs
    return coeffs, ycalc, dropped


def solve_linear(basis_phases: np.ndarray, grid: np.ndarray, yobs: np.ndarray,
                 sigma: np.ndarray | None, n_bg: int = 3,
                 bg_mode: str = "cheb") -> tuple[np.ndarray, np.ndarray]:
    """契约版入口：返回 (coeffs, ycalc)，coeffs = [S_1..S_P, b_0..b_{n_bg-1}]。"""
    coeffs, ycalc, _dropped = solve_linear_detail(
        basis_phases, grid, yobs, sigma, n_bg, bg_mode)
    return coeffs, ycalc
