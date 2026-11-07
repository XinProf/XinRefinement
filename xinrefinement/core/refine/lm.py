# vendored from PolyXRD-RutAna :: rutana/core/refine/lm.py
"""B 法精修 · Levenberg–Marquardt 优化器（T4.3，自写约 60 行核心）。

设计决策 D2：不依赖 scipy 优化器（scipy 仅用于 lstsq），LM 自写：
- 数值 Jacobian：中心差分，步长 1e-4·max(1, |x|)（相对/绝对混合步长）
- 解 (JᵀJ + λ·diag(JᵀJ))·δ = −Jᵀr（Marquardt 缩放，接近二阶收敛且数值稳定）
- 一次试探成功降低代价 -> λ /= 3；失败 -> λ *= 3 重试
- bounds 用参数裁剪（每步 clip），简单可靠
- 收敛：连续两次迭代代价相对改善 < ftol，或 |δ| < xtol，或达 max_iter
- 兜底：λ > 1e8 仍无法降低代价 -> success=False，返回当前最优 x
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

LAMBDA_MAX = 1e8


@dataclass(frozen=True)
class LMResult:
    """LM 最小化结果。cost = 0.5·Σ r²。"""

    x: np.ndarray
    success: bool
    n_iter: int
    cost: float
    message: str


def _jacobian(residual_fn, x: np.ndarray, step: float = 1e-4) -> np.ndarray:
    """中心差分数值 Jacobian，shape (m, n)。

    ``step`` 为相对步长基值（``h = step·max(1, |x_j|)``）。默认 1e-4 与
    vendor 原样一致；v1.5 M7 起可由 ``RefineConfig.lm_step`` 覆盖，用于
    对齐 MAUD ``Marquardt LS`` 的导数步长做对照实验。

    注意：中心差分的试探点 `x±h` 在参数位于下界时**会越界**（如 TCH 尺寸项
    Y 的初值 0 恰在下界，试探 -1e-4）。这会让 LM 无法把参数推离下界 ——
    实测真实 NCA_80_15_05 样品 Y 恒为 0（尺寸项被压死，晶粒尺寸误报"超出检出
    上限"）。

    **本函数刻意保持 vendor 原样**（T6.4d 评估后回退）：改成边界感知的
    单边差分后，LM 的梯度尺度变化会改变收敛路径，反而把已锚定的 T2.3
    行为带偏（实测"尺寸+应变"配置 Rwp 3.2058 → 3.8941，size_only 从
    3.1624 → 3.6581，落在更差的局部极小）。非凸问题上"梯度更准"不等于
    "解更好"。TCH 参数的边界病态改在**初值侧**规避 ——
    见 `nca/core/constants.py` 的 `TCH_SIZE_INIT_Y` / `TCH_STRAIN_INIT_X`
    与 `nca/core/solve.py` 的 `SolveOptions.to_profile_params()`。
    """
    r0 = np.asarray(residual_fn(x), dtype=np.float64)
    J = np.empty((r0.size, x.size), dtype=np.float64)
    for j in range(x.size):
        h = step * max(1.0, abs(x[j]))
        xp = x.copy(); xp[j] += h
        xm = x.copy(); xm[j] -= h
        J[:, j] = (np.asarray(residual_fn(xp), float)
                   - np.asarray(residual_fn(xm), float)) / (2.0 * h)
    return J


def lm_minimize(residual_fn, x0: np.ndarray, *, bounds=None, max_iter: int = 60,
                ftol: float = 1e-8, xtol: float = 1e-8,
                lambda0: float = 1e-3, step: float = 1e-4) -> LMResult:
    """最小化 0.5·||residual_fn(x)||²。

    residual_fn(x) -> 1D 残差向量；bounds: (lo, hi) 数组对或 None。
    ``lambda0``（初始 λ）与 ``step``（雅可比相对步长）是 v1.5 M7 暴露的
    对齐旋钮，默认值与 v1.0 起的历史行为一致（逐位不变）。
    """
    x = np.clip(np.asarray(x0, dtype=np.float64).copy(),
                *(bounds if bounds is not None else (None, None)))
    r = np.asarray(residual_fn(x), dtype=np.float64)
    cost = 0.5 * float(r @ r)
    lam = float(lambda0)
    n_iter = 0
    msg = "max_iter 达到上限"
    consecutive_small = 0
    ever_accepted = False

    while n_iter < max_iter:
        J = _jacobian(residual_fn, x, step)
        JTJ = J.T @ J
        g = -(J.T @ r)
        diag = np.diag(JTJ).copy()
        diag[diag <= 0.0] = 1e-12
        accepted = False
        while lam <= LAMBDA_MAX:
            delta = np.linalg.solve(
                JTJ + lam * np.diag(diag), g)
            if not np.all(np.isfinite(delta)):
                lam *= 3.0
                continue
            x_new = np.clip(x + delta,
                            *(bounds if bounds is not None else (None, None)))
            r_new = np.asarray(residual_fn(x_new), dtype=np.float64)
            cost_new = 0.5 * float(r_new @ r_new)
            if np.isfinite(cost_new) and cost_new < cost:
                improvement = (cost - cost_new) / max(cost, 1e-300)
                x, r, cost = x_new, r_new, cost_new
                lam = max(lam / 3.0, 1e-12)
                accepted = True
                ever_accepted = True
                n_iter += 1
                if improvement < ftol:
                    consecutive_small += 1
                else:
                    consecutive_small = 0
                if np.max(np.abs(delta)) < xtol or consecutive_small >= 2:
                    msg = "收敛（代价改善 < ftol 或步长 < xtol）"
                    return LMResult(x, True, n_iter, cost, msg)
                break
            lam *= 3.0
        if not accepted:
            # 已有进展后 λ 溢出 = 已处于（局部）极小, 无进一步下降 -> 收敛;
            # 从未接受任何一步才是真失败。
            if ever_accepted:
                return LMResult(x, True, n_iter, cost,
                                "收敛（λ 达上限, 无进一步下降）")
            return LMResult(x, False, n_iter, cost,
                            "λ 超过上限仍无法降低代价（可能已处于局部极小）")
    # 达到 max_iter：仅 λ 兜底失败才算失败（此时已在上面提前 return）
    return LMResult(x, True, n_iter, cost, msg)
