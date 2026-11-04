# vendored from PolyXRD-RutAna :: rutana/core/profile/shape.py
"""vendor: 峰形函数纯函数子集（T3.2）。

Vendored from PolyXRD-SynthPattern xrd_synth_engine.py — © 2026 PolyXRD Team,
dual-licensed (Academic/Commercial)，家族内复用。
复制范围: resolve_wavelengths / march_dollase_weight / _pv_peak /
pseudo_voigt_grid / caglioti / constant_fwhm 及其常量依赖。
除删除未用常量外逐行照抄，禁止改动数值。
"""
from __future__ import annotations

import math

import numpy as np

# Cu Kα1 波长 (Å)
DEFAULT_WAVELENGTH = 1.5406

# Kα1 / Kα2 波长 (Å)。按 2:1 加权 ((2·α1 + α2)/3) 即常见教科书里的 "Kα" 值。
KA_DOUBLET = {
    "Cu": (1.54056, 1.54439, 0.5),
    "Co": (1.78897, 1.79285, 0.5),
    "Cr": (2.28970, 2.29361, 0.5),
    "Fe": (1.93604, 1.93998, 0.5),
    "Mo": (0.70930, 0.71359, 0.5),
    "Ag": (0.55941, 0.56381, 0.5),
}
DEFAULT_KA_RATIO = 0.5
DEFAULT_FWHM = 0.15


def resolve_wavelengths(wavelength: float = DEFAULT_WAVELENGTH,
                        anode: str | None = None,
                        ka_ratio: float = DEFAULT_KA_RATIO) -> list[tuple[float, float]]:
    """返回 [(波长(Å), 权重)], 权重归一化 -> 总积分强度守恒。

    anode=None: 单色光 [(wavelength, 1.0)]。
    anode="Cu": [(Kα1, 1/(1+r)), (Kα2, r/(1+r))], 默认 r = Iα2/Iα1 = 0.5。
    """
    if anode is None:
        return [(float(wavelength), 1.0)]
    key = anode.strip() if isinstance(anode, str) else None
    if key not in KA_DOUBLET:
        raise ValueError(
            f"未知阳极: {anode} (可选: {', '.join(KA_DOUBLET)})")
    w1, w2, _default_ratio = KA_DOUBLET[key]
    ratio = DEFAULT_KA_RATIO if ka_ratio is None else float(ka_ratio)
    if ratio < 0:
        raise ValueError("Iα2/Iα1 不能为负")
    tot = 1.0 + ratio
    return [(w1, 1.0 / tot), (w2, ratio / tot)]


def march_dollase_weight(cos_alpha: float, r: float) -> float:
    """March–Dollase 择优取向权重: W = (r²cos²α + r⁻¹sin²α)^(-3/2)。

    r = 1 -> 恒等于 1 (无择优); r < 1 片状/板状惯习; r > 1 针状/柱状惯习。
    """
    if abs(r - 1.0) < 1e-12:
        return 1.0
    c2 = min(max(cos_alpha * cos_alpha, 0.0), 1.0)
    return float((r * r * c2 + (1.0 - c2) / r) ** -1.5)


def _pv_peak(g: np.ndarray, pos: float, fwhm: float, eta: float) -> np.ndarray:
    """单个 pseudo-Voigt 峰（单位峰高）。"""
    x = (g - pos) / fwhm
    G = np.exp(-4 * math.log(2) * x * x)
    L = 1.0 / (1.0 + 4 * x * x)
    return eta * L + (1 - eta) * G


def pseudo_voigt_grid(peaks, grid: np.ndarray, fwhm_func, eta: float = 0.5) -> np.ndarray:
    """peaks: list[(pos, height)]; fwhm_func(pos)->fwhm(deg)。

    eta 可为标量或 eta(pos) 可调用对象（尺寸/应变展宽时逐峰变化）。"""
    prof = np.zeros_like(grid)
    eta_of = eta if callable(eta) else (lambda _p: eta)
    for pos, height in peaks:
        if height <= 0:
            continue
        fwhm = max(fwhm_func(pos), 1e-4)
        prof += height * _pv_peak(grid, pos, fwhm, eta_of(pos))
    return prof


def caglioti(U: float, V: float, W: float):
    """返回 fwhm(pos) 函数 (Caglioti: FWHM^2 = U tan^2θ + V tanθ + W)。"""
    def f(pos: float) -> float:
        t = math.tan(math.radians(pos))
        return math.sqrt(max(U * t * t + V * t + W, 1e-6))
    return f


def constant_fwhm(val: float):
    """常数 FWHM 函数。"""
    return lambda pos: val
