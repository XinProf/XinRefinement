# vendored from PolyXRD-RutAna :: rutana/core/profile/forward.py
"""B 法前向模型（T3.2 新增代码）：单相计算谱。

compute_phase_profile 返回**任意单位的 phase-only 曲线**：
- 不做任何归一化（标度留给线性层 S_p）
- 不加背景（背景是线性参数）
- 不加噪声（噪声只属于合成/实测数据）

数学: y(2θ) = Σ_hkl |F_hkl|²·LP(θ)·Ω(2θ − 2θ_hkl − zero)，Ω = pseudo-Voigt，
FWHM² 由 Caglioti 公式 U·tan²θ + V·tanθ + W 给出，anode 启用 Kα1/α2 双线。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.shape import (
    DEFAULT_WAVELENGTH,
    _pv_peak,
    march_dollase_weight,
    resolve_wavelengths,
)
from xinrefinement.core.profile.size_strain import split_fwhm  # NCA 修改（T2.1）
from xinrefinement.core.profile.struct import compute_peaks

# FWHM 下限保护：防止 Caglioti 退化导致除零
MIN_W = 1e-4


def caglioti_2theta(U: float, V: float, W: float):
    """Caglioti 公式（正确的 2θ 口径）：FWHM² = U·tan²θ + V·tanθ + W，θ = 2θ/2。

    输入 pos 为 2θ（度）。注：家族 vendor 的 shape.caglioti 实现为 tan(2θ)
    （SynthPattern 原始引擎即如此调用，属家族级历史语义，其文档串写 tanθ 但
    代码求值于全角）；Rietveld 物理要求 tanθ，且 tan(2θ) 在 2θ>90° 后变负、
    FWHM 曲线完全失真——v1.0.0 真实数据实证这是 U,V→0 角点收敛的直接原因
    （精修器被迫用常数 W + 大 bfactor 补偿高角，Rwp 10.97% → 修后 9.5%）。
    为不破坏家族 vendor 冻结约定，在 RutAna 侧按正确口径包装。
    """
    def f(pos: float) -> float:
        t = math.tan(math.radians(pos) / 2.0)
        return math.sqrt(max(U * t * t + V * t + W, 1e-6))
    return f


@dataclass(frozen=True)
class ProfileParams:
    """B 法非线性峰形参数集。

    zero : 零点偏移 (度)，直接加在峰位上
    U,V,W: Caglioti FWHM² = U·tan²θ + V·tanθ + W
    eta  : pseudo-Voigt Lorentz 占比
    anode: 阳极靶 (启用 Kα1/α2 双线)；None = 单色光
    ka_ratio: Iα2/Iα1
    po_r : 每相 March–Dollase 择优取向 {phase_name: (h,k,l,r)}，None = 无
    wavelength: 基准波长 (Å)，仅 anode=None 时使用
    asym : 峰不对称度（低角尾展宽，s = asym/tanθ，v1.0.0 实测数据需要）
    bfactor: 经验高角衰减 exp(−B/2d²)（补偿 Debye-Waller/吸收类高角强度
             系统性偏差；v1.0.0 真实数据实测 B≈0.2，合成数据默认 0 = 关闭）
    integrated: True = 峰高按积分强度归一化（h/(FWHM·(1.06447+0.50633η))），
             这是 Rietveld 标量 S 的标准口径（Hill–Howard 定量依赖它）；
             v0.1.0 旧口径（峰高直乘）仅用于对照，False 时不归一化。
    microabs: 每相 Brindley 微吸收校正 {phase_name: μ·r}（v1.2.0，默认 None=关）。
             因子 (1−e^(−μr))/(μr) 乘到该相计算强度上（MAUD
             MicroAbsorptionBrindley 同式；μr→0 极限为 1，即无校正）。
             μ·r = 线吸收系数 × 平均晶粒半径；高吸收相（Fe 相/萤石等）给大值。
             v1.2.0 只施加不精修——μ·r 由调用方按物理估计给出。
    """

    zero: float = 0.0
    U: float = 0.0
    V: float = 0.0
    W: float = 0.02
    eta: float = 0.5
    anode: str | None = "Cu"
    ka_ratio: float = 0.5
    po_r: dict | None = None
    wavelength: float = DEFAULT_WAVELENGTH
    asym: float = 0.0
    bfactor: float = 0.0
    integrated: bool = True
    # ---- NCA 修改（T2.1）：TCH 尺寸-应变洛伦兹项 ----
    # X = 4ε（应变，度）；Y = Kλ/D（尺寸，度）。两者全 0 时行为与
    # vendor 版**逐位一致**（走纯 Caglioti + 固定 eta），保证 golden 不漂。
    # X/Y 非零时 η 由 TCH 公式按 (ΓG, ΓL) 逐峰给出，prm.eta 被忽略。
    X: float = 0.0
    Y: float = 0.0
    # ---- v1.2.0：Brindley 微吸收（每相 μ·r，None = 全部关闭） ----
    microabs: dict | None = None


def brindley_factor(mr: float) -> float:
    """Brindley 微吸收因子 ``(1 − e^(−μr)) / (μr)``（μr→0 极限 = 1）。

    ``mr`` = 线吸收系数 μ (μm⁻¹) × 平均晶粒半径 r (μm)。参照
    MAUD ``MicroAbsorptionBrindley``（Rietquan 2.3 同式）：
    高 μ 相的观测强度被压低，校正把该相计算强度乘以 <1 的因子，
    精修后其标度因子（→ wt%）相应抬回。
    """
    mr = float(mr)
    if not math.isfinite(mr) or mr <= 0.0:
        return 1.0
    if mr < 1e-4:
        # 小 μr：1-e^(-x) 灾难性消元，走 Taylor 展开 1 - x/2 + x²/6
        return 1.0 - mr / 2.0 + mr * mr / 6.0
    return (1.0 - math.exp(-mr)) / mr


def _window_slice(grid: np.ndarray, pos: float, half: float) -> tuple[int, int]:
    """峰 ±half 度窗口对应的网格下标区间 [i0, i1)（含边界修正）。"""
    i0 = int(np.searchsorted(grid, pos - half, side="left"))
    i1 = int(np.searchsorted(grid, pos + half, side="right"))
    return max(i0, 0), min(i1, grid.size)


# 衍射峰枚举缓存：peaks 只依赖 (结构, 波长, 窗口, po 的 hkl 部分)，与
# zero/U/V/W/eta 及 March–Dollase r 无关。v1.4.0 起缓存键只含 po 的
# (h,k,l) 部分——r 变化不再击穿缓存（PO 精修每次残差评估只廉价重加权）。
_PEAKS_CACHE: dict[tuple, tuple] = {}
_PEAKS_CACHE_MAX = 256


def _phase_peaks(struct: CifStructure, prm: ProfileParams,
                 tmin: float, tmax: float):
    """计算该相的衍射峰与择优取向贡献明细，带缓存。

    返回 ``(peaks, detail, skipped)``：po 非 None 时 peaks 以 r=1.0
    计算（PO 权重由 :func:`_apply_po_r` 按当前 r 前向施加），detail 为
    ``compute_peaks(po_detail=True)`` 的贡献明细（与 peaks 逐项对齐）；
    po 为 None 时 detail 为 None。
    """
    po = None
    if prm.po_r:
        po = prm.po_r.get(struct.name)
    po_hkl = (int(po[0]), int(po[1]), int(po[2])) if po is not None else None
    # NCA 修改（T3.1）：键中含结构变体盐值。占位/z_O 精修每次评估都会新建
    # CifStructure（同 name/cell/原子数），CPython 的地址复用可能让新旧结构
    # 撞出相同 id() -> 陈旧峰强。变体盐值保证占位变体永不互撞。
    key = (id(struct), struct.name, struct.cell, len(struct.atoms),
           getattr(struct, "_variant", 0),
           prm.anode, prm.ka_ratio, prm.wavelength, float(tmin), float(tmax),
           po_hkl)
    hit = _PEAKS_CACHE.get(key)
    if hit is None:
        comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
        if po is None:
            peaks, skipped = compute_peaks(struct, prm.wavelength, tmin, tmax,
                                           po=None, wavelengths=comps)
            hit = (peaks, None, skipped)
        else:
            # r 固定取 1.0：峰位/权重在明细路径外与实际 r 解耦
            peaks, skipped, detail = compute_peaks(
                struct, prm.wavelength, tmin, tmax,
                po=(po[0], po[1], po[2], 1.0), wavelengths=comps,
                po_detail=True)
            hit = (peaks, detail, skipped)
        if len(_PEAKS_CACHE) >= _PEAKS_CACHE_MAX:
            _PEAKS_CACHE.clear()
        _PEAKS_CACHE[key] = hit
    return hit


def _po_r_of(prm: ProfileParams, struct: CifStructure) -> float | None:
    """该相当前的 March–Dollase r（无 po_r 或未配置该相时返回 None）。"""
    if not prm.po_r:
        return None
    po = prm.po_r.get(struct.name)
    if po is None:
        return None
    return float(po[3])


def _apply_po_r(peaks, detail, r: float):
    """按 March–Dollase r 重算各峰积分强度（O(峰数)，精修每次评估可承受）。

    数值与直接传 po=(h,k,l,r) 给 compute_peaks 完全一致（明细预存
    val_pre_po 与 cos_alpha，此处只按新 r 加权求和）；r=1 或无明细时
    零开销返回原 peaks。
    """
    if r == 1.0 or not detail:
        return peaks
    out = []
    for (pos, _val, d), contribs in zip(peaks, detail):
        i = 0.0
        for v, ca in contribs:
            i += v * march_dollase_weight(ca, r)
        if i > 0:
            out.append((pos, i, d))
    return out


def _peaks_with_po(prm: ProfileParams, struct: CifStructure,
                   tmin: float, tmax: float):
    """取该相峰列表并按 prm.po_r 中的 r 施加择优取向权重。"""
    peaks, detail, _skipped = _phase_peaks(struct, prm, tmin, tmax)
    if detail is not None:
        r = _po_r_of(prm, struct)
        if r is not None and r != 1.0:
            peaks = _apply_po_r(peaks, detail, r)
    return peaks


def _asym_split(pos_shifted: float, fwhm: float, asym: float) -> tuple[float, float]:
    """不对称峰形的左右 FWHM：s = asym/tanθ，左尾 (1+s)·FWHM、右尾 (1−s)·FWHM。

    低角衍射的轴向发散不对称随 tanθ 增大而减弱（v1.0.0 实测数据实证）。
    """
    if asym == 0.0:
        return fwhm, fwhm
    th = math.radians(max(pos_shifted, 1e-3) / 2.0)
    s = max(-0.85, min(0.85, asym / max(math.tan(th), 1e-3)))
    return fwhm * (1.0 + s), fwhm * (1.0 - s)


def _add_peak_windowed(prof: np.ndarray, grid: np.ndarray,
                       pos: float, height: float, fwhm: float, eta: float,
                       asym: float = 0.0, bfactor: float = 0.0,
                       d: float | None = None,
                       integrated: bool = True) -> None:
    """把单个峰只累加到 ±(8·FWHM + 0.05°) 窗口内（T4.8 性能路径）。

    pseudo-Voigt 在 8 个 FWHM 之外幅值 < 2e-5（Lorentz 尾巴），对 Rwp 的影响
    远低于计数噪声，与全网格计算逐点偏差 RMS < 1e-6·max。
    integrated=True 时 height 先除以 pV 峰面积换算系数，转为积分强度口径。
    """
    if bfactor > 0.0 and d is not None and d > 0:
        height = height * math.exp(min(50.0, -bfactor / (2.0 * d * d)))
    if integrated:
        height = height / max(fwhm * (1.06447 + 0.50633 * eta), 1e-12)
    fl, fr = _asym_split(pos, fwhm, asym)
    half = 8.0 * max(fl, fr) + 0.05
    i0, i1 = _window_slice(grid, pos, half)
    if i1 <= i0:
        return
    x = grid[i0:i1] - pos
    if fl == fr:
        prof[i0:i1] += height * _pv_peak(grid[i0:i1], pos, fwhm, eta)
    else:
        # 左右不同 FWHM 的分段 pseudo-Voigt（在峰位处拼接，峰位值连续）
        left = height * _pv_peak(x / fl * fwhm + pos, pos, fwhm, eta)
        right = height * _pv_peak(x / fr * fwhm + pos, pos, fwhm, eta)
        prof[i0:i1] += np.where(x < 0, left, right)


def compute_phase_profile_naive(struct: CifStructure, grid: np.ndarray,
                                prm: ProfileParams,
                                tmin: float = 5.0, tmax: float = 90.0) -> np.ndarray:
    """全网格参考实现（慢，供 T4.8 一致性测试对照）。"""
    peaks = _peaks_with_po(prm, struct, tmin, tmax)
    fwhm_func = caglioti_2theta(prm.U, prm.V, max(prm.W, MIN_W))
    prof = np.zeros_like(grid, dtype=np.float64)
    tch_on = (prm.X != 0.0) or (prm.Y != 0.0)   # NCA 修改（T2.1）
    for pos, height, d in peaks:
        if height <= 0:
            continue
        if tch_on:
            # NCA 修改（T2.1）: TCH 逐峰 FWHM 与 η（prm.eta 被忽略）
            fwhm, eta, _fl = split_fwhm(pos, prm.U, prm.V, max(prm.W, MIN_W),
                                        prm.X, prm.Y)
            fwhm = max(fwhm, MIN_W)
        else:
            fwhm = max(fwhm_func(pos), MIN_W)
            eta = prm.eta
        _add_peak_windowed(prof, grid, pos + prm.zero, height, fwhm, eta,
                           prm.asym, prm.bfactor, d, prm.integrated)
    return _apply_microabs(prof, prm, struct)


def compute_phase_profile(struct: CifStructure, grid: np.ndarray,
                          prm: ProfileParams,
                          tmin: float = 5.0, tmax: float = 90.0) -> np.ndarray:
    """计算单相计算谱（窗口化，无归一化/无背景/无噪声）。

    struct  : CifStructure（全晶胞原子）
    grid    : 2θ 网格 (度, 升序)
    prm     : 峰形参数
    tmin,tmax: 衍射峰枚举窗口（度）
    返回 float64 数组，与 grid 等长，全非负、最大值 > 0（晶胞合法时）。
    """
    grid = np.asarray(grid, dtype=np.float64)
    peaks = _peaks_with_po(prm, struct, tmin, tmax)
    fwhm_func = caglioti_2theta(prm.U, prm.V, max(prm.W, MIN_W))
    prof = np.zeros_like(grid, dtype=np.float64)
    tch_on = (prm.X != 0.0) or (prm.Y != 0.0)   # NCA 修改（T2.1）
    for pos, height, d in peaks:
        if height <= 0:
            continue
        if tch_on:
            # NCA 修改（T2.1）: TCH 逐峰 FWHM 与 η（prm.eta 被忽略）
            fwhm, eta, _fl = split_fwhm(pos, prm.U, prm.V, max(prm.W, MIN_W),
                                        prm.X, prm.Y)
            fwhm = max(fwhm, MIN_W)
        else:
            fwhm = max(fwhm_func(pos), MIN_W)
            eta = prm.eta
        _add_peak_windowed(prof, grid, pos + prm.zero, height, fwhm, eta,
                           prm.asym, prm.bfactor, d, prm.integrated)
    return _apply_microabs(prof, prm, struct)


def _apply_microabs(prof: np.ndarray, prm: ProfileParams,
                    struct: CifStructure) -> np.ndarray:
    """按相施加 Brindley 微吸收因子（v1.2.0）。

    ``microabs`` 缺相 / 值 ≤0 / 非有限一律视为不校正（因子 1），
    保证旧调用方与 golden **逐位不变**。
    """
    if not prm.microabs:
        return prof
    mr = prm.microabs.get(struct.name)
    if not mr:
        return prof
    f = brindley_factor(mr)
    if f == 1.0:
        return prof
    return prof * f


def strongest_peak_position(struct: CifStructure, prm: ProfileParams,
                            tmin: float = 5.0, tmax: float = 90.0) -> float:
    """最强衍射峰的 2θ 位置（不含 zero），供 QA 与测试。"""
    peaks = _peaks_with_po(prm, struct, tmin, tmax)
    if not peaks:
        raise ValueError(f"{struct.name}: 窗口内无衍射峰")
    return max(peaks, key=lambda t: t[1])[0]


def phase_profile_at(prms: dict[str, ProfileParams], structs: list[CifStructure],
                     grid: np.ndarray, tmin: float = 5.0,
                     tmax: float = 90.0) -> np.ndarray:
    """各相 profile 矩阵，shape (n_phase, N)，按 structs 顺序堆叠。"""
    rows = [compute_phase_profile(s, grid, prms[s.name], tmin, tmax)
            for s in structs]
    return np.vstack(rows)
