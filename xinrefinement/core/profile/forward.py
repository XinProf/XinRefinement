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
from xinrefinement.core.profile.struct import compute_peaks, reciprocal_basis

# FWHM 下限保护：防止 Caglioti 退化导致除零
MIN_W = 1e-4

# ---- v1.3 任务 #14：EWIMV 离散 ODF（纤维织构 1D） ----
#: χ 网格点数（0–90°，5° 步长，端点含）
TEXTURE_N_GRID = 19
#: 织构因子边界（与 MAUD「负 ODF 截断」同方向，用边界而非截断）
TEXTURE_BOUNDS = (0.1, 10.0)
#: 默认织构轴（(001) 纤维轴，BB 几何最常见）
DEFAULT_TEXTURE_AXIS = (0, 0, 1)

# ---- v1.3 任务 #15：Popa LB 各向异性尺寸/应变（2 阶截断，Cholesky 参数化） ----
#: 尺寸项 L 的对角/非对角边界（Å⁻¹）；非对角可负（任意取向椭球）
ANISO_SIZE_BOUNDS = (1.0e-4, 1.6)
ANISO_SIZE_CROSS = (-1.6, 1.6)
#: 应变项 L 的对角/非对角边界（无量纲）
ANISO_STRAIN_BOUNDS = (1.0e-6, 0.1)
ANISO_STRAIN_CROSS = (-0.1, 0.1)
#: L 的参数位次（行优先下三角）：0=l11 1=l21 2=l22 3=l31 4=l32 5=l33
ANISO_DIAG_IDX = (0, 2, 5)
_RAD2DEG = 180.0 / math.pi
SCHERRER_K = 0.9


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
    # ---- v1.3 任务 #14：EWIMV 离散 ODF 织构（每相，None = 关闭） ----
    #: ``{phase_name: {"axis": (h0, k0, l0), "grid": [T(χ_0) … T(χ_90)]}}``
    #: v1 仅 Bragg–Brentano 平板对称反射几何：散射矢量恒沿样品法向，织构
    #: 因子退化为每反射常数 ``T(χ_hkl)``（χ 为该反射法向与织构轴夹角）。
    #: **开织构的相自动忽略 po_r**（同一自由度不给两套模型抢，结果里告警）。
    texture: dict | None = None
    # ---- v1.3 任务 #15：Popa LB 各向异性尺寸/应变（每相，None = 关闭） ----
    #: ``{phase_name: {"size": [c11,c22,c33,c12,c13,c23],
    #:               "strain": [同序]}}``
    #: 2 阶球谐截断：``1/D² = Σ c_ij n_i n_j``、``ε² = Σ c_ij n_i n_j``，
    #: ``n`` 为该反射的笛卡尔单位法向。各向同性时 c 为对角常数，等价于
    #: 标量 X/Y。给出 aniso 的相**忽略标量 X/Y**（每峰按方向取值）。
    aniso: dict | None = None


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


def default_texture_grid() -> list[float]:
    """无织构的 T(χ) 初值（全 1.0，19 点）。"""
    return [1.0] * TEXTURE_N_GRID


def normalize_texture_grid(grid=None, n: int = TEXTURE_N_GRID) -> list[float]:
    """把任意长度的 T(χ) 序列规范成 n 点（缺省全 1.0，线性重采样）。"""
    g = [float(v) for v in (grid or [])]
    if not g:
        return [1.0] * n
    if len(g) == n:
        return g
    src = np.linspace(0.0, 90.0, len(g))
    dst = np.linspace(0.0, 90.0, n)
    return [float(v) for v in np.interp(dst, src, np.asarray(g))]


def texture_chi(hkl, axis, cell) -> float:
    """晶面 (hkl) 法向与织构轴 ``axis`` 的夹角（度，0–90）。

    用倒易基矢算夹角（非正交晶系不能直接用 hkl 点积）。``cell`` 为
    ``(a, b, c, α, β, γ)``。
    """
    a, b, c, al, be, ga = cell
    ast, bst, cst = reciprocal_basis(a, b, c, al, be, ga)
    v1 = int(hkl[0]) * ast + int(hkl[1]) * bst + int(hkl[2]) * cst
    v2 = int(axis[0]) * ast + int(axis[1]) * bst + int(axis[2]) * cst
    n1, n2 = float(np.linalg.norm(v1)), float(np.linalg.norm(v2))
    if n1 <= 0.0 or n2 <= 0.0:
        return 0.0
    # 纤维织构只关心「与轴的夹角」，取 |cos| 折到 [0°, 90°]（χ 与 180−χ 等价）
    cos_a = abs(float(v1 @ v2)) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))


def texture_factor(chi_deg: np.ndarray, grid) -> np.ndarray:
    """按 χ（度）在织构网格上线性插值取 T(χ)。"""
    g = np.asarray(grid, dtype=np.float64)
    if g.size == 0:
        return np.ones_like(np.asarray(chi_deg, dtype=np.float64))
    if g.size == 1:
        return np.full_like(np.asarray(chi_deg, dtype=np.float64), g[0])
    chi_grid = np.linspace(0.0, 90.0, g.size)
    return np.interp(np.asarray(chi_deg, dtype=np.float64), chi_grid, g)


def texture_chi_buckets(struct: CifStructure, prm: "ProfileParams", axis,
                        tmin: float = 5.0,
                        tmax: float = 90.0) -> tuple[int, np.ndarray]:
    """相内独立 χ 桶数（5° 分桶去重）与全部 χ 值——织构可辨识性护栏。

    返回 ``(n_buckets, chis)``。``n_buckets < 3`` 时该相开织构属于欠定
    （不能分辨多于两个自由度的形状），调用方应显式报错而非静默给出结果。
    """
    comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
    _peaks, _skipped, detail = compute_peaks(
        struct, prm.wavelength, tmin, tmax,
        po=(int(axis[0]), int(axis[1]), int(axis[2]), 1.0),
        wavelengths=comps, po_detail=True)
    chis: list[float] = []
    for contribs in detail:
        for _v, ca in contribs:
            chis.append(math.degrees(math.acos(
                max(-1.0, min(1.0, abs(ca))))))
    arr = np.array(chis, dtype=np.float64)
    if arr.size == 0:
        return 0, arr
    return int(np.unique(np.floor(arr / 5.0)).size), arr


def _apply_texture(peaks, detail, grid):
    """按 T(χ) 重算各峰积分强度（O(峰数)，精修每次评估可承受）。

    ``detail`` 来自 ``compute_peaks(po_detail=True)``（po 取织构轴、r=1），
    每项 ``(val_pre, cos_alpha)``。数值与「在 compute_peaks 内逐 hkl 乘
    T(χ)」等价；T 变化只重算乘法，峰列表缓存不失效。
    """
    g = np.asarray(grid, dtype=np.float64)
    if g.size < 2 or not detail:
        return peaks
    out = []
    for entry, contribs in zip(peaks, detail):
        if not contribs:
            continue
        arr = np.asarray(contribs, dtype=np.float64)
        chi = np.degrees(np.arccos(np.clip(np.abs(arr[:, 1]), 0.0, 1.0)))
        i = float(np.sum(arr[:, 0] * texture_factor(chi, g)))
        if i > 0:
            out.append((entry[0], i, entry[2]) + tuple(entry[3:]))
    return out


def aniso_xy(entry: dict, n, wavelength: float) -> tuple[float, float]:
    """Popa LB（2 阶截断）逐反射 (X, Y)——单位与 TCH 标量一致（度）。

    ``1/D² = Σ c_ij n_i n_j`` 给出 ``Y = (180/π)·Kλ/√(1/D²)``；
    ``ε² = Σ c_ij n_i n_j`` 给出 ``X = (180/π)·4√ε²``。二次型取非负截断。
    """
    nx, ny, nz = float(n[0]), float(n[1]), float(n[2])

    def _quad(c) -> float:
        """|Lᵀ·n|（L = 行优先下三角），即 sqrt(Σ c_ij n_i n_j) 的可导形式。"""
        c = list(c or ())
        if len(c) < 6:
            c = list(c) + [0.0] * (6 - len(c))
        v1 = c[0] * nx
        v2 = c[1] * nx + c[2] * ny
        v3 = c[3] * nx + c[4] * ny + c[5] * nz
        return math.sqrt(v1 * v1 + v2 * v2 + v3 * v3)

    inv_d = _quad(entry.get("size"))
    eps = _quad(entry.get("strain"))
    y_deg = _RAD2DEG * SCHERRER_K * wavelength * inv_d
    x_deg = _RAD2DEG * 4.0 * eps
    return x_deg, y_deg


def aniso_default(wavelength: float, x_deg: float = 0.0,
                  y_deg: float = 0.0) -> dict:
    """由标量 (X, Y) 构造各向同性起点（对角二次型，交叉项 0）。"""
    inv_d = (y_deg / (_RAD2DEG * SCHERRER_K * wavelength)) if y_deg > 0 else 1.0e-3
    eps = (math.pi / 180.0) * x_deg / 4.0 if x_deg > 0 else 1.0e-6
    # 各向同性 -> L = diag(inv_d, inv_d, inv_d)
    return {"size": [inv_d, 0.0, inv_d, 0.0, 0.0, inv_d],
            "strain": [eps, 0.0, eps, 0.0, 0.0, eps]}


def aniso_ratios(entry: dict) -> tuple[float, float]:
    """各向异性比 (Dmax/Dmin, εmax/εmin)——诊断/告警（各向同性时均为 1）。

    L 的奇异值即「最大/最小 1/D（或 ε）」：比 = σmax/σmin。
    """
    def _ratio(c):
        c = list(c or ())
        if len(c) < 6:
            c = list(c) + [0.0] * (6 - len(c))
        mat = np.array([[c[0], 0.0, 0.0],
                        [c[1], c[2], 0.0],
                        [c[3], c[4], c[5]]], dtype=np.float64)
        sv = np.linalg.svd(mat, compute_uv=False)
        lo, hi = float(sv[-1]), float(sv[0])
        if hi <= 1e-12:
            return 1.0
        if lo <= 1e-12:
            return math.inf
        return hi / lo
    return _ratio(entry.get("size")), _ratio(entry.get("strain"))


def aniso_dirs(struct: CifStructure, prm: "ProfileParams",
               tmin: float = 5.0, tmax: float = 90.0,
               tol: float = 0.05) -> np.ndarray:
    """窗口内各反射的**独立**晶向数（0.05 精度去重）——各向异性可辨识性护栏。

    12 个二次型系数至少需要 8 个不同方向才能被约束；方向重复时（如只用
    低角几条 00l 反射）结果不可辨识，调用方应显式报错。
    """
    comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
    peaks, _skipped = compute_peaks(struct, prm.wavelength, tmin, tmax,
                                    wavelengths=comps, with_dirs=True)
    dirs = []
    for peak in peaks:
        if len(peak) < 4:
            continue
        n = np.round(np.asarray(peak[3], dtype=np.float64) / tol).astype(np.int64)
        dirs.append(tuple(int(v) for v in n))
    return np.unique(np.array(dirs, dtype=np.int64), axis=0) if dirs else np.zeros((0, 3))


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
    # v1.3 #14：织构相以织构轴充当明细路径的参考矢量（T(χ) 前向施加），
    # 且**忽略** po_r（两套模型抢同一自由度，见 ProfileParams.texture）。
    tex = prm.texture.get(struct.name) if prm.texture else None
    if tex is not None:
        axis = tex["axis"]
        po_hkl = (int(axis[0]), int(axis[1]), int(axis[2]))
        po = (po_hkl[0], po_hkl[1], po_hkl[2], 1.0)
    else:
        po_hkl = (int(po[0]), int(po[1]), int(po[2])) if po is not None else None
    # NCA 修改（T3.1）：键中含结构变体盐值。占位/z_O 精修每次评估都会新建
    # CifStructure（同 name/cell/原子数），CPython 的地址复用可能让新旧结构
    # 撞出相同 id() -> 陈旧峰强。变体盐值保证占位变体永不互撞。
    aniso = prm.aniso.get(struct.name) if prm.aniso else None
    key = (id(struct), struct.name, struct.cell, len(struct.atoms),
           getattr(struct, "_variant", 0),
           prm.anode, prm.ka_ratio, prm.wavelength, float(tmin), float(tmax),
           po_hkl, aniso is not None)
    hit = _PEAKS_CACHE.get(key)
    if hit is None:
        comps = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
        if po is None:
            peaks, skipped = compute_peaks(struct, prm.wavelength, tmin, tmax,
                                           po=None, wavelengths=comps,
                                           with_dirs=aniso is not None)
            hit = (peaks, None, skipped)
        else:
            # r 固定取 1.0：峰位/权重在明细路径外与实际 r 解耦
            peaks, skipped, detail = compute_peaks(
                struct, prm.wavelength, tmin, tmax,
                po=(po[0], po[1], po[2], 1.0), wavelengths=comps,
                po_detail=True, with_dirs=aniso is not None)
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
    for entry, contribs in zip(peaks, detail):
        i = 0.0
        for v, ca in contribs:
            i += v * march_dollase_weight(ca, r)
        if i > 0:
            # 透传第 4 元素（各向异性用的晶向），保持下游解包一致
            out.append((entry[0], i, entry[2]) + tuple(entry[3:]))
    return out


def _peaks_with_po(prm: ProfileParams, struct: CifStructure,
                   tmin: float, tmax: float):
    """取该相峰列表并按 prm.po_r / prm.texture 施加权重（织构优先）。

    开织构的相按 ``T(χ_hkl)`` 加权并**忽略**该相 March–Dollase r；
    否则按 r 施加择优取向（v1.4.0 语义不变）。
    """
    peaks, detail, _skipped = _phase_peaks(struct, prm, tmin, tmax)
    if detail is None:
        return peaks
    tex = prm.texture.get(struct.name) if prm.texture else None
    if tex is not None:
        return _apply_texture(peaks, detail, tex.get("grid"))
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
    prof = np.zeros_like(grid, dtype=np.float64)
    _accumulate_peaks(prof, grid, peaks, prm, struct)
    return _apply_microabs(prof, prm, struct)


def _accumulate_peaks(prof: np.ndarray, grid: np.ndarray, peaks,
                      prm: ProfileParams, struct: CifStructure) -> None:
    """把峰列表累加进 prof（窗口化）；支持 TCH 标量与 Popa LB 各向异性。

    ``prm.aniso`` 含该相时按每峰晶向取 (X, Y)（**忽略**标量 X/Y）；
    (X, Y) 均为 0 时退回 Caglioti + prm.eta，与未开各向异性的行为一致。
    """
    fwhm_func = caglioti_2theta(prm.U, prm.V, max(prm.W, MIN_W))
    tch_on = (prm.X != 0.0) or (prm.Y != 0.0)   # NCA 修改（T2.1）
    aniso = prm.aniso.get(struct.name) if prm.aniso else None
    for peak in peaks:
        pos, height, d = peak[0], peak[1], peak[2]
        if height <= 0:
            continue
        x_deg, y_deg = prm.X, prm.Y
        if aniso is not None:
            n = peak[3] if len(peak) > 3 else (0.0, 0.0, 1.0)
            x_deg, y_deg = aniso_xy(aniso, n, prm.wavelength)
        if x_deg != 0.0 or y_deg != 0.0:
            # NCA 修改（T2.1）: TCH 逐峰 FWHM 与 η（prm.eta 被忽略）
            fwhm, eta, _fl = split_fwhm(pos, prm.U, prm.V, max(prm.W, MIN_W),
                                        x_deg, y_deg)
            fwhm = max(fwhm, MIN_W)
        else:
            fwhm = max(fwhm_func(pos), MIN_W)
            eta = prm.eta
        _add_peak_windowed(prof, grid, pos + prm.zero, height, fwhm, eta,
                           prm.asym, prm.bfactor, d, prm.integrated)


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
    prof = np.zeros_like(grid, dtype=np.float64)
    _accumulate_peaks(prof, grid, peaks, prm, struct)
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
