"""参数相关性矩阵（T3.2 · 新建，非 vendor）。

收敛点处由数值 Jacobian 估计参数相关性：
    H = JᵀJ（高斯-牛顿 Hessian）→ cov = H⁻¹（协方差，未含 σ² 标度，
    但相关系数对公共标度不敏感）→ r_ij = cov_ij / √(cov_ii·cov_jj)。

两个入口：
1. `corr_from_jacobian`：通用数学层。nonlinear.refine 在 `refine_corr=True`
   时于收敛点调用，结果挂到 `RefineResult.correlation`（追加字段）。
2. `occ_profile_correlations`：占位相关项专用 —— 跨两段式精修的参数
   （Li占位/z_O ↔ B因子/标度/择优取向 r）不能从任何单一 residual_fn 拿到，
   这里用**显式参数向量**重建联合残差（背景曲线固定为收敛值）：
   x = [occ_Li, z_O] + 可选 [bfactor, scale, po_r]。

口径说明：背景固定。背景（平滑低频）与峰形/占位参数（峰局部）近似正交，
固定背景对相关系数是一阶无碍的近似；报告里引用相关值时应注明该口径。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import compute_phase_profile
from xinrefinement.core.refine.lm import _jacobian
from xinrefinement.core.refine.occ import apply_occ_zo

#: 相关性报告默认阈值：|r| 超过它才进"高相关警告"清单
CORR_WARN = 0.7


@dataclass(frozen=True)
class CorrResult:
    """相关性矩阵 + 参数标签（顺序与参数向量一致）。"""

    labels: tuple[str, ...]
    matrix: np.ndarray

    def against(self, label: str) -> dict[str, float]:
        """某参数与其余参数的相关系数 {label: r}（不含自身）。"""
        i = self.labels.index(label)
        return {self.labels[j]: float(self.matrix[i, j])
                for j in range(len(self.labels)) if j != i}

    def high_pairs(self, min_abs: float = CORR_WARN) -> list[tuple[str, str, float]]:
        """|r| ≥ min_abs 的参数对（上三角，按 |r| 降序）。"""
        out = []
        n = len(self.labels)
        for i in range(n):
            for j in range(i + 1, n):
                r = float(self.matrix[i, j])
                if abs(r) >= min_abs:
                    out.append((self.labels[i], self.labels[j], r))
        out.sort(key=lambda t: -abs(t[2]))
        return out

    def as_dict(self) -> dict:
        return {"labels": list(self.labels),
                "matrix": [[round(float(v), 4) for v in row]
                           for row in self.matrix]}


def corr_from_jacobian(J: np.ndarray) -> np.ndarray:
    """数值 Jacobian (m×n) → 相关系数矩阵 (n×n)。

    用 pinv 防 H 奇异（病态参数组合恰是相关性诊断的对象，不能因奇异崩掉）。
    """
    J = np.asarray(J, dtype=np.float64)
    if J.ndim != 2 or J.shape[1] == 0:
        return np.zeros((J.shape[1] if J.ndim == 2 else 0,) * 2)
    cov = np.linalg.pinv(J.T @ J)
    d = np.sqrt(np.abs(np.diag(cov)))
    d = np.where(d > 0, d, 1.0)
    return cov / np.outer(d, d)


def pack_labels(cfg, n_phase: int, po_names: list[str] | None = None) -> tuple[str, ...]:
    """与 nonlinear._pack 严格同序的参数标签（新增开关必须同步这里）。"""
    labels: list[str] = []
    if cfg.refine_zero:
        labels.append("zero")
    if cfg.refine_uvw:
        labels.extend(["U", "V", "W"])
    if cfg.refine_eta:
        labels.append("eta")
    if cfg.refine_asym:
        labels.append("asym")
    if cfg.refine_bfactor:
        labels.append("bfactor")
    if cfg.refine_cell:
        for j in range(n_phase):
            labels.extend([f"cell_a[{j}]", f"cell_c[{j}]"])
    for name in (po_names or []):
        labels.append(f"po_r[{name}]")
    # NCA 修改（T2.1）：_pack 末尾先 X 后 Y
    if getattr(cfg, "refine_strain", False):
        labels.append("X")
    if getattr(cfg, "refine_size", False):
        labels.append("Y")
    return tuple(labels)


# ---------------------------------------------------------------------------
# 占位相关项（跨两段式精修的联合参数向量）
# ---------------------------------------------------------------------------
def occ_profile_correlations(phase: CifStructure, pat: Pattern, prm, sites,
                             occ: float, zo: float, bg_curve: np.ndarray,
                             with_bfactor: bool = True,
                             with_scale: bool = True,
                             with_po: bool = False,
                             po_hkl: tuple | None = None,
                             tmin: float = 5.0, tmax: float = 90.0,
                             ) -> CorrResult:
    """Li占位 ↔ B因子 / 标度 / 择优取向 的相关系数（T4 结果卡出口）。

    bg_curve : 收敛解的背景曲线（逐点强度）—— 固定不参与求导。
    po_hkl   : with_po=True 时必填 (h,k,l)；r 初值取 prm.po_r 里该相的当前值。
    """
    from dataclasses import replace

    tt = pat.two_theta
    yo = pat.intensity
    sig = np.sqrt(np.maximum(yo, 1.0))
    bg = np.asarray(bg_curve, dtype=np.float64)

    labels = ["occ_Li", "z_O"]
    if with_bfactor:
        labels.append("bfactor")
    if with_scale:
        labels.append("scale")
    if with_po:
        if po_hkl is None:
            raise ValueError("with_po=True 需要 po_hkl=(h,k,l)")
        labels.append(f"po_r[{phase.name}]")

    b0 = prm.bfactor
    if with_po:
        cur = (prm.po_r or {}).get(phase.name)
        r0 = float(cur[3]) if cur else 1.0
    s0 = 1.0

    def f(x: np.ndarray) -> np.ndarray:
        st = apply_occ_zo(phase, sites, float(x[0]), float(x[1]))
        b = float(x[2]) if with_bfactor else b0
        s = float(x[2 + int(with_bfactor)]) if with_scale else s0
        kw = {}
        if with_bfactor:
            kw["bfactor"] = b
        if with_po:
            r = float(x[-1])
            kw["po_r"] = {phase.name: (po_hkl[0], po_hkl[1], po_hkl[2], r)}
        row = compute_phase_profile(st, tt, replace(prm, **kw), tmin, tmax)
        ycalc = s * row + bg
        return (yo - ycalc) / sig

    x0 = [occ, zo]
    if with_bfactor:
        x0.append(b0)
    if with_scale:
        x0.append(s0)
    if with_po:
        x0.append(r0)
    J = _jacobian(f, np.array(x0, dtype=np.float64))
    return CorrResult(labels=tuple(labels), matrix=corr_from_jacobian(J))
