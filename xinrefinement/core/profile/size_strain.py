"""TCH 尺寸-应变峰形（T2.1 · 新建，非 vendor）。

Thompson–Cox–Hastings (1987) 伪 Voigt：把仪器高斯宽化与样品洛伦兹宽化
合成一条 FWHM 曲线与逐峰混合系数 η。

为什么必须加这一项（T1.4 实测，见 docs/VALIDATION.md）
------------------------------------------------------
纯 Caglioti 拟合真实 NCA_80_15_05 时 U 收敛到 0、经验高角衰减 B 被迫涨到 0.52
（结构更差的起点会到 3.3）——模型缺尺寸/应变宽化时，拟合器只能用
"压低高角强度"这种非物理手段去补偿。TCH 给出物理上正确的宽化来源，
尺寸 D 与应变 ε 才能作为**输出量**报给用户。

口径（与 docs/STD_FREEZE.md §3 一致）
------------------------------------
高斯项（Caglioti，仪器）:  FWHM_G² = U·tan²θ + V·tanθ + W
洛伦兹项（样品）:          FWHM_L  = X·tanθ + Y/cosθ
    其中 X = 4ε（应变，度）、Y = Kλ/D（尺寸，度）——两者都是**常数**，
    随角度的变化全部由 tanθ / cosθ 承载。
合成:                      FWHM = (ΓG⁵ + 2.69269 ΓG⁴ΓL + … + ΓL⁵)^(1/5)
混合:                      η = 1.36603 q − 0.47719 q² + 0.11116 q³, q = ΓL/Γ

注意：Y 的量纲是"度"，D = (180/π)·K·λ/Y；X 同理，ε = (π/180)·X/4。
STD_FREEZE v1 里写的 "D = Kλ/(Y·cosθ)" 是笔误，已在 v2 修正。
"""
from __future__ import annotations

import math

#: TCH 合成多项式系数（Thompson, Cox & Hastings, J. Appl. Cryst. 20 (1987) 445）
_TCH_COEFF = (1.0, 2.69269, 2.42843, 4.47163, 0.07842, 1.0)

#: Scherrer 常数（球形微晶，体积加权口径）
SCHERRER_K = 0.89
#: 弧度 -> 度
_RAD2DEG = 180.0 / math.pi
#: 最小 FWHM 保护（度），与 vendor forward.MIN_W 同量级
MIN_FWHM = 1e-4


def _bragg_terms(pos_deg: float) -> tuple[float, float]:
    """返回 (tanθ, cosθ)，θ = pos/2 的弧度（与 vendor caglioti_2theta 同口径）。"""
    th = math.radians(max(pos_deg, 1e-6)) / 2.0
    return math.tan(th), math.cos(th)


def fwhm_gaussian(pos_deg: float, U: float, V: float, W: float,
                  basis: str = "tan", wavelength: float = 1.5406) -> float:
    """Caglioti 高斯项 FWHM_G（度）。

    ``basis="tan"``（默认，历史行为）：FWHM² = U·tan²θ + V·tanθ + W。
    ``basis="d"``（v1.5 M5）：FWHM² = U·x² + V·x + W，x = 2sinθ/λ = 1/d，
    高角饱和不发散。**必须与 ``forward.width_function`` 同口径**，否则开了
    Popa LB 各向异性的相会静默退回 tan 基（宽度模型的换基就失效了）。
    """
    if basis == "d":
        x = 2.0 * math.sin(math.radians(max(pos_deg, 1e-6)) / 2.0) / wavelength
        return math.sqrt(max(U * x * x + V * x + W, MIN_FWHM * MIN_FWHM))
    t, _c = _bragg_terms(pos_deg)
    return math.sqrt(max(U * t * t + V * t + W, MIN_FWHM * MIN_FWHM))


def fwhm_lorentz(pos_deg: float, X: float, Y: float) -> float:
    """洛伦兹项 FWHM_L = X·tanθ + Y/cosθ（度）。X/Y 为 0 时返回 0。"""
    if X == 0.0 and Y == 0.0:
        return 0.0
    t, c = _bragg_terms(pos_deg)
    return max(X * t + Y / max(c, 1e-9), 0.0)


def tch_combine(fg: float, fl: float) -> float:
    """TCH 五次多项式合成总 FWHM（度）。"""
    if fl <= 0.0:
        return max(fg, MIN_FWHM)
    if fg <= 0.0:
        return max(fl, MIN_FWHM)
    g, l = fg, fl
    s = 0.0
    for coef, term in zip(_TCH_COEFF, (g**5, g**4 * l, g**3 * l**2,
                                       g**2 * l**3, g * l**4, l**5)):
        s += coef * term
    return max(s ** 0.2, MIN_FWHM)


def tch_eta(fg: float, fl: float) -> float:
    """TCH 有效混合系数 η ∈ (0, 1]。纯高斯 -> 0，纯洛伦兹 -> 1。"""
    if fl <= 0.0:
        return 0.0
    tot = tch_combine(fg, fl)
    q = min(max(fl / max(tot, MIN_FWHM), 0.0), 1.0)
    eta = 1.36603 * q - 0.47719 * q * q + 0.11116 * q ** 3
    return min(max(eta, 0.0), 1.0)


def split_fwhm(pos_deg: float, U: float, V: float, W: float,
               X: float, Y: float, basis: str = "tan",
               wavelength: float = 1.5406) -> tuple[float, float, float]:
    """一次算齐 (总 FWHM, η, FWHM_L) —— 前向模型逐峰调用。"""
    fg = fwhm_gaussian(pos_deg, U, V, W, basis=basis, wavelength=wavelength)
    fl = fwhm_lorentz(pos_deg, X, Y)
    return tch_combine(fg, fl), tch_eta(fg, fl), fl


# ---------------------------------------------------------------------------
# 物理量反演（T2.2 的底层）
# ---------------------------------------------------------------------------
def size_from_y(y_deg: float, wavelength: float, k: float = SCHERRER_K) -> float:
    """由洛伦兹尺寸项 Y（度）反演相干衍射畴尺寸 D（Å）。

    β_size(2θ) = Kλ/(D·cosθ) -> Y = (180/π)·Kλ/D -> D = (180/π)·Kλ/Y。
    Y <= 0 表示未启用尺寸项，返回 inf。
    """
    if y_deg <= 0.0:
        return math.inf
    return _RAD2DEG * k * wavelength / y_deg


def strain_from_x(x_deg: float) -> float:
    """由洛伦兹应变项 X（度）反演微观应变 ε（无量纲）。

    β_strain(2θ) = 4ε·tanθ -> X = (180/π)·4ε -> ε = (π/180)·X/4。
    """
    if x_deg <= 0.0:
        return 0.0
    return (math.pi / 180.0) * x_deg / 4.0


def y_from_size(d_angstrom: float, wavelength: float,
                k: float = SCHERRER_K) -> float:
    """正向：由 D（Å）算 Y（度）—— 合成虚拟样时用。"""
    if d_angstrom <= 0:
        raise ValueError(f"D 必须为正: {d_angstrom}")
    return _RAD2DEG * k * wavelength / d_angstrom


def x_from_strain(eps: float) -> float:
    """正向：由 ε 算 X（度）。"""
    if eps < 0:
        raise ValueError(f"ε 不能为负: {eps}")
    return (180.0 / math.pi) * 4.0 * eps
