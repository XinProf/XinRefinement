"""P1.5 · 参数标准偏差 e.s.d.（变量投影下的 Schur 补协方差）。

为什么需要 Schur 补
-------------------
引擎用变量投影（separable NLS）：线性参数
``c = [S_1..S_P, b_0..b_{n_bg-1}]``（相标度 + 背景系数）在每次迭代内由
``lstsq`` **解析消去**，LM 只迭代非线性参数 ``x``。若只对 ``x`` 的
reduced Jacobian 求协方差，会得到**偏小**的 e.s.d.，而且拿不到 scale /
背景 / 物相含量的不确定度——定量结果恰恰依赖 scale。

设加权设计矩阵 ``Ã = A/σ``（列 = 各相 profile + 背景基），
``Jf = ∂(A c/σ)/∂x``（固定 c 时对 x 的导数）。全参数
``θ = (x, c)`` 的 Hessian 近似为

    H = [[JfᵀJf, −JfᵀÃ], [−ÃᵀJf, ÃᵀÃ]]

对 ``B = ÃᵀÃ`` 取 **Schur 补**

    S = Jfᵀ (I − Ã B⁺ Ãᵀ) Jf = Jfᵀ P⊥ Jf

则（``s² = rᵀr/(m−n)`` 为方差估计）：

    Cov_xx = s² S⁺                       ← 非线性参数
    Cov_cc = s² [B⁺ + B⁺ÃᵀJf S⁺ JfᵀÃ B⁺]  ← scale/背景
    Cov_xc = −s² S⁺ JfᵀÃ B⁺

``JfᵀP⊥Jf`` 同时等于「每次重新解 c 的 reduced 残差 Jacobian」的
``JᵀJ``（因为 Ãᵀr=0 时 dr/dx ≈ P⊥·Jf）——本模块用这两条独立路径
互相校验，构成验收里的「Schur 补一致性检查」。

物相含量 e.s.d. 由 Hill–Howard ``w_p = S_p(ZMV)_p / Σ S_q(ZMV)_q``
对 scale 协方差做一阶误差传播。

本模块是**独立后处理**（输入 ``SolveResult``），不改精修主路径 → golden 零风险。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import compute_phase_profile
from xinrefinement.core.refine.linear import background_basis, solve_linear_detail
from xinrefinement.core.refine.qpa import qpa_inputs_from_cif
from xinrefinement.core.refine.solve import SolveResult


@dataclass(frozen=True)
class EsdResult:
    """e.s.d. 与相关性结果。"""

    labels: tuple[str, ...]
    esd: tuple[float, ...]                 # 全参数 θ=(x,c) 的 e.s.d.
    covariance: np.ndarray                 # 全参数协方差 (n×n)
    correlation: np.ndarray                # 全参数相关系数 (n×n)
    scale_esd: tuple[float, ...]           # 各相标度 e.s.d.
    weight_esd_pct: tuple[float, ...] | None  # 物相含量 e.s.d.（百分点）
    variance_factor: float                 # s²
    schur_consistency: float               # |S_red − S_schur| 相对差（<0.05 合格）
    n_points: int
    n_params: int


def _num_jacobian(fn, x: np.ndarray, h: float = 1e-5) -> np.ndarray:
    """中心差分 Jacobian (m×n)，fn 返回一维数组。"""
    x = np.asarray(x, dtype=np.float64)
    f0 = np.asarray(fn(x), dtype=np.float64)
    J = np.empty((f0.size, x.size), dtype=np.float64)
    for j in range(x.size):
        step = h * max(1.0, abs(x[j]))
        xp, xm = x.copy(), x.copy()
        xp[j] += step
        xm[j] -= step
        J[:, j] = (np.asarray(fn(xp), float) - np.asarray(fn(xm), float)) / (2 * step)
    return J


def estimate_esd(phases: list[CifStructure], res: SolveResult,
                 formulas: dict[str, str] | None = None,
                 step: float = 1e-5) -> EsdResult:
    """由一次精修结果估计全参数 e.s.d.（含被消去的线性参数）。

    TCH 切换边界（实测发现）：引擎在 ``X == Y == 0`` 时关闭 TCH 合并
    （``tch_on`` 切换），且 TCH-on 分支的 η 是**计算值**而非 ``prm.eta``
    ——两分支在原点不连续（v50 配方链实测：轻推 X/Y 到 0.01 后 Rwp 从
    5.85% 劣化到 14.4%）。若精修后 X/Y 恰好停在 0（LM 触界），其导数
    在数学上无定义，任何 ±h 扰动都会跨越分支切换，使「reduced
    Jacobian ≡ Schur 补」恒等式失效（实测一致性 0.36）。处理：**不做
    轻推**（那会改变模型、虚高 s²），而是把停在边界的 X/Y 列从 e.s.d.
    与一致性检查中**剔除**（其 e.s.d. 记为 NaN），其余参数照常。
    """
    cfg = res.config
    pat = res.pattern
    prm_base = res.params
    tt, yo = pat.two_theta, pat.intensity
    # v1.2.0：与主引擎同口径（weight_mode），否则 e.s.d. 与 Rwp 权重不一致
    from xinrefinement.core.refine.nonlinear import effective_sigma
    sig = effective_sigma(cfg, pat)
    n_phase = len(phases)
    n_bg = len(res.background)
    cell = [tuple(c) for c in (res.engine.cell_scales
                               or [(1.0, 1.0)] * n_phase)]

    # 复用生产路径的注册表，保证参数顺序/取值与 refine 完全一致
    from xinrefinement.core.params.registry import build_registry_from_config
    from xinrefinement.core.refine.nonlinear import _scaled

    po_names = sorted(prm_base.po_r) if prm_base.po_r else []
    reg = build_registry_from_config(cfg, prm_base, n_phase, po_names)
    x_final = reg.pack(prm_base, cell_scales=cell, po_r=prm_base.po_r)
    p = x_final.size

    # TCH 切换边界列：恰为 0 的 X/Y（tch_on 分支开关处导数无定义）
    keep = np.ones(p, dtype=bool)
    for j, lab in enumerate(reg.labels()):
        if lab.endswith(".micro.X") or lab.endswith(".micro.Y"):
            if x_final[j] == 0.0:
                keep[j] = False

    def design(x: np.ndarray):
        """返回 (r, Ã, c, ycalc)；c 每次重解（reduced 路径）。"""
        prm, cl, _po = reg.unpack(x, prm_base, cell_scales=cell,
                                  po_r=prm_base.po_r)
        structs = [_scaled(phases[i], cl[i][0], cl[i][1])
                   for i in range(n_phase)]
        bp = np.vstack([compute_phase_profile(s, tt, prm, cfg.tmin, cfg.tmax)
                        for s in structs])
        bg = background_basis(tt, n_bg, cfg.bg_mode)
        coeffs, ycalc, _dropped = solve_linear_detail(
            bp, tt, yo, sig, n_bg, cfg.bg_mode)
        A = np.hstack([bp.T, bg])
        Aw = A / sig[:, None]
        return (yo - ycalc) / sig, Aw, coeffs, A, prm, bp, bg

    r0, Aw, c, A, _prm, _bp, _bg = design(x_final)
    q = Aw.shape[1]
    m = r0.size

    # ---- 路径 1：reduced 残差 Jacobian（c 随 x 重解）----
    j_red = _num_jacobian(lambda x: design(x)[0], x_final, step)

    # ---- 路径 2：固定 c 的 ycalc Jacobian -> Schur 补 ----
    def ycalc_fixed(x: np.ndarray) -> np.ndarray:
        prm, cl, _po = reg.unpack(x, prm_base, cell_scales=cell,
                                  po_r=prm_base.po_r)
        structs = [_scaled(phases[i], cl[i][0], cl[i][1])
                   for i in range(n_phase)]
        bp = np.vstack([compute_phase_profile(s, tt, prm, cfg.tmin, cfg.tmax)
                        for s in structs])
        bg = background_basis(tt, n_bg, cfg.bg_mode)
        return (np.hstack([bp.T, bg]) @ c) / sig

    jf = _num_jacobian(ycalc_fixed, x_final, step)  # ∂(A c/σ)/∂x
    B = Aw.T @ Aw
    # 列均衡化：相标度 ~1e-2 与背景系数 ~1e2 量级悬殊（cond(B) ~ 1e9），
    # 直接 pinv 会损失投影精度；投影到 col(A) 对列缩放不变，均衡化是安全的。
    d_col = np.sqrt(np.abs(np.diag(B)))
    d_col = np.where(d_col > 0, d_col, 1.0)
    Aw_e = Aw / d_col[None, :]
    B_e = Aw_e.T @ Aw_e
    B_e_inv = np.linalg.pinv(B_e)
    B_inv = (1.0 / d_col)[:, None] * B_e_inv * (1.0 / d_col)[None, :]
    P_perp = np.eye(m) - Aw_e @ B_e_inv @ Aw_e.T

    # 边界列（TCH 切换处的 X/Y）在一致性检查与协方差中剔除
    jr_k = j_red[:, keep]
    jf_k = jf[:, keep]
    s_red = jr_k.T @ jr_k
    s_schur = jf_k.T @ P_perp @ jf_k
    consistency = (float(np.linalg.norm(s_red - s_schur))
                   / max(float(np.linalg.norm(s_schur)), 1e-12))

    # ---- 协方差组装（只对 well-defined 列）----
    n_total = p + q
    dof = max(m - n_total, 1)
    s2 = float(r0 @ r0) / dof
    pk = int(keep.sum())
    s_inv = np.linalg.pinv(s_schur) if pk else np.zeros((0, 0))
    jta = jf_k.T @ Aw if pk else np.zeros((0, q))
    cov_xx = s2 * s_inv
    cov_xc = (-s2 * (s_inv @ jta @ B_inv)) if pk else np.zeros((0, q))
    cov_cc = s2 * (B_inv + B_inv @ (jta.T @ s_inv @ jta) @ B_inv) if pk \
        else s2 * B_inv

    cov = np.full((n_total, n_total), np.nan)
    if pk:
        k_idx = np.flatnonzero(keep)
        cov[np.ix_(k_idx, k_idx)] = cov_xx
        cov[np.ix_(k_idx, np.arange(p, n_total))] = cov_xc
        cov[np.ix_(np.arange(p, n_total), k_idx)] = cov_xc.T
    cov[p:, p:] = cov_cc

    d = np.sqrt(np.abs(np.diag(cov)))          # 边界列为 NaN
    d_finite = np.where(np.isfinite(d), d, 0.0)
    d_safe = np.where(d_finite > 0, d_finite, 1.0)
    corr = np.where(np.isfinite(cov), cov, 0.0) / np.outer(d_safe, d_safe)

    labels = (tuple(reg.labels())
              + tuple(f"scale[{i}]" for i in range(n_phase))
              + tuple(f"bg[{j}]" for j in range(n_bg)))
    scale_esd = tuple(float(v) for v in d[p:p + n_phase])

    # ---- 物相含量误差传播 ----
    weight_esd = None
    try:
        fs = formulas or {}
        kvals = []
        for st in phases:
            z, v, mass = qpa_inputs_from_cif(st, fs.get(st.name))
            kvals.append(z * v * mass)
        k = np.asarray(kvals, dtype=float)
        scales = c[:n_phase]
        denom = float(scales @ k)
        if denom > 0:
            cov_ss = cov[p:p + n_phase, p:p + n_phase]
            out = []
            for i in range(n_phase):
                grad = np.zeros(n_phase)
                for j in range(n_phase):
                    grad[j] = k[i] * ((denom if j == i else 0.0)
                                      - scales[i] * k[j]) / denom ** 2
                out.append(100.0 * math.sqrt(max(float(grad @ cov_ss @ grad), 0.0)))
            weight_esd = tuple(out)
    except Exception:
        weight_esd = None

    return EsdResult(
        labels=labels, esd=tuple(float(v) for v in d), covariance=cov,
        correlation=corr, scale_esd=scale_esd, weight_esd_pct=weight_esd,
        variance_factor=s2, schur_consistency=consistency,
        n_points=m, n_params=n_total)
