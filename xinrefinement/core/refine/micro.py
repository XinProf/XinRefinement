"""P2.6 · 微结构输出：由 TCH 峰形参数反演晶粒尺寸 D 与微观应变 ε。

底层反演来自 ``core.profile.size_strain``（已验证）：
``Y = Kλ/D``（度）→ ``D = (180/π)·Kλ/Y``（Å）；
``X = 4ε``（度）→ ``ε = (π/180)·X/4``。
本模块把它们整理成可展示/可导出的结构化结果，并处理 Y/X=0 的
「未启用 / 超出检出上限」语义。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.profile.size_strain import (
    SCHERRER_K,
    size_from_y,
    strain_from_x,
    y_from_size,
    x_from_strain,
)


@dataclass(frozen=True)
class MicroResult:
    size_angstrom: float | None     # 相干衍射畴尺寸 D（Å）；None = 未检出
    size_nm: float | None
    strain: float                    # 无量纲微观应变 ε
    strain_pct: float
    Y_deg: float
    X_deg: float
    wavelength: float
    note: str


def resolve_wavelength(prm: ProfileParams) -> float:
    """取实际用于前向模型的 Kα1 波长（Å）。"""
    if prm.anode is None:
        return float(prm.wavelength)
    from xinrefinement.core.profile.shape import resolve_wavelengths
    lines = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
    return float(max(lines, key=lambda t: t[1])[0])


def microstructure(prm: ProfileParams, k: float = SCHERRER_K) -> MicroResult:
    """由精修后的 ProfileParams 反演 D 与 ε。"""
    lam = resolve_wavelength(prm)
    Y, X = float(prm.Y), float(prm.X)
    D = size_from_y(Y, lam, k) if Y > 0 else None
    eps = strain_from_x(X) if X > 0 else 0.0
    if D is None:
        note = "尺寸项 Y=0：晶粒超出检出上限或尺寸项未启用（不是无限大晶粒）"
    else:
        note = f"D = {D:.1f} Å（相干衍射畴，非 SEM 二次颗粒）"
    return MicroResult(
        size_angstrom=D, size_nm=(None if D is None else D / 10.0),
        strain=eps, strain_pct=eps * 100.0,
        Y_deg=Y, X_deg=X, wavelength=lam, note=note)


def synth_terms(size_angstrom: float | None, strain: float,
                wavelength: float) -> tuple[float, float]:
    """虚拟样合成用：由物理量反算 X/Y（与 microstructure 互逆）。"""
    Y = 0.0 if size_angstrom is None else y_from_size(size_angstrom, wavelength)
    X = x_from_strain(strain)
    return X, Y


def roundtrip_check(size_angstrom: float, strain: float,
                    wavelength: float) -> tuple[float, float]:
    """正反演误差（验收 <5%）。返回 (D 相对误差, ε 相对误差)。"""
    X, Y = synth_terms(size_angstrom, strain, wavelength)
    from xinrefinement.core.profile.size_strain import size_from_y, strain_from_x
    d_back = size_from_y(Y, wavelength)
    e_back = strain_from_x(X)
    return (abs(d_back - size_angstrom) / size_angstrom,
            abs(e_back - strain) / max(strain, 1e-12))
