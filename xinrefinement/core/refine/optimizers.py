"""优化器插拔（v1.3 任务 #16）。

把「用哪个非线性最小二乘求解器」从 ``nonlinear.refine`` 的 if/else 里抽出来，
做成**按名字查表**的可扩展结构：新增优化器只需写一个 ``_run_xxx`` 并登记。

约定（所有实现必须遵守）
------------------------
- 输入：``residual(x) -> 1D ndarray``（已加权残差，可能带罚项块）、初值 ``x0``、
  上下界 ``(lo, hi)``（逐元素）；
- 输出：:class:`OptimizeResult`（x / cost / success / nfev / message）；
- ``cost`` 一律为 ``0.5·||r||²``（与自研 LM 同口径，重启比较才能直接比）；
- 不抛异常表「失败」—— 只有配置错误（未知方法、scipy 缺失）才抛。

当前方法
--------
``lm``     自研 Levenberg–Marquardt（有界投影 + 数值差分），默认；与 v1.0 起
           的历史结果逐位一致，是回归基线。
``trf``    ``scipy.optimize.least_squares(method="trf", x_scale="jac")``：
           真实数据（多相关联形状参数）上更稳，v1.0.0 实证 Rwp 11.6→9.5%；
           ``backend="scipy"`` 是它的历史别名。
``dogbox`` scipy 的信赖域狗腿法，对**强边界约束**（大量参数贴在边界上，
           如织构网格 T(χ) 触界）比 trf 收敛更快，但更依赖初值。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OptimizeResult:
    """统一的优化结果（cost 与自研 LM 同口径）。"""

    x: np.ndarray
    cost: float
    success: bool
    nfev: int = 0
    message: str = ""


#: 方法名 -> 说明（GUI/CLI 的 choices 与文档都从这里取）
OPTIMIZERS: dict[str, str] = {
    "lm": "自研 Levenberg–Marquardt（默认，有界投影）",
    "trf": "scipy trf（真实数据推荐，x_scale=jac）",
    "dogbox": "scipy dogbox（强边界约束场景）",
}
#: 历史别名
ALIASES = {"scipy": "trf"}


def resolve_method(method: str) -> str:
    """别名归一化并校验；未知方法列出可用项（不静默回退）。"""
    key = ALIASES.get(str(method or "lm"), str(method or "lm"))
    if key not in OPTIMIZERS:
        raise ValueError(
            f"未知优化器 {method!r}（可选: {', '.join(sorted(OPTIMIZERS))}；"
            f"别名: {', '.join(sorted(ALIASES))}）")
    return key


def _cost(residual, x) -> float:
    r = np.asarray(residual(x), dtype=np.float64)
    return 0.5 * float(r @ r)


def _run_lm(residual, x0, lo, hi, max_iter: int, **kw) -> OptimizeResult:
    from xinrefinement.core.refine.lm import lm_minimize

    nfev = [0]
    on_eval = kw.get("on_eval")

    def counted(xv):
        nfev[0] += 1
        if on_eval is not None:
            on_eval(nfev[0])
        return residual(xv)

    # v1.5 M7：λ 初值与雅可比步长可调（对齐 MAUD Marquardt LS 的
    # λ=0.01 / 步长 1e-4）；不给时用历史默认，逐位不变。
    lm = lm_minimize(counted, x0, bounds=(lo, hi), max_iter=max_iter,
                     lambda0=float(kw.get("lambda0", 1e-3)),
                     step=float(kw.get("step", 1e-4)))
    return OptimizeResult(x=np.asarray(lm.x, float), cost=float(lm.cost),
                          success=bool(lm.success),
                          nfev=nfev[0] if nfev[0] else getattr(lm, "nfev", 0))


def _run_scipy(residual, x0, lo, hi, max_iter: int, method: str = "trf",
               **kw) -> OptimizeResult:
    try:
        from scipy.optimize import least_squares
    except Exception:                 # scipy 缺失 -> 回退自研 LM（历史行为）
        return _run_lm(residual, x0, lo, hi, max_iter)

    nfev = [0]
    on_eval = kw.get("on_eval")

    def counted(xv):
        nfev[0] += 1
        if on_eval is not None:
            on_eval(nfev[0])
        return residual(xv)

    sr = least_squares(counted, x0, bounds=(lo, hi), method=method,
                       x_scale="jac", max_nfev=max(3000, 40 * max_iter))
    return OptimizeResult(x=np.asarray(sr.x, float), cost=float(sr.cost),
                          success=bool(sr.success), nfev=nfev[0],
                          message=str(sr.message))


def minimize(residual, x0, bounds, method: str = "lm",
             max_iter: int = 40, **kw) -> OptimizeResult:
    """按名字选择优化器（唯一入口）。"""
    key = resolve_method(method)
    x0 = np.asarray(x0, dtype=np.float64)
    lo, hi = bounds
    if key == "lm":
        return _run_lm(residual, x0, lo, hi, max_iter, **kw)
    return _run_scipy(residual, x0, lo, hi, max_iter,
                      method=("dogbox" if key == "dogbox" else "trf"), **kw)
