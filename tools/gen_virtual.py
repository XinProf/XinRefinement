"""P1-PRE · 参数化虚拟样合成器（P1/P2 验收地基）。

与 P0 的 ``tools/bench_b.py`` 不同：本模块**自包含**（只用 ``xinrefinement.core``，
不跨仓引用 PolyXRD-SynthPattern），可参数化合成**任意晶系 / 多相 / 零点 /
样品位移 / 弯背景 / 择优取向 / 尺寸-应变 / 含量 / 波长 / 噪声**的已知真值谱，
seed 可复现，并冻结 golden 真值 JSON 供 round-trip 验收比对。

物理标度（Hill–Howard 自洽，关键）
----------------------------------
Rietveld 相标度 ``S_p ∝ w_p / (Z_p·M_p·V_p)``；定量反算
``w_p ∝ S_p·Z_p·M_p·V_p``。故合成时令 ``frac_p ∝ w_p/(Z·M·V)`` 再整体
归一化，QPA 才能把质量分数原样收回来。这与 ``bench_b.py`` 里因
SynthPattern 内部 ``scale=frac/V`` 而做的 ``frac ∝ w/(Z·M)`` 换算**口径不同但
等价**（本模块直接乘 frac，不再除 V）。

噪声模型
--------
默认泊松计数噪声（与 Rietveld 权重 ``w=1/σ², σ²≈y`` 自洽），否则常数强噪声
在计数统计权重下会把 Rwp 虚高到 ~30%（RutAna v1.0.0 实证）。

运行::

    D:/Project/XRD/python310/python.exe tools/gen_virtual.py --out tests/data/virtual_p1
    D:/Project/XRD/python310/python.exe tools/gen_virtual.py --out DIR --preset tio2
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xinrefinement.core.refine.linear import background_basis  # noqa: E402
from xinrefinement.core.dtypes import Pattern  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import (  # noqa: E402
    ProfileParams,
    compute_phase_profile,
)
from xinrefinement.core.refine.qpa import qpa_inputs_from_cif  # noqa: E402


@dataclass(frozen=True)
class PhaseSpec:
    """一个物相的合成输入。"""

    cif: str                       # CIF 路径（相对项目根或绝对）
    weight_pct: float              # 质量分数真值
    formula: str | None = None     # 缺省回退 CIF ``_chemical_formula_sum``
    po_hkl: tuple[int, int, int] | None = None
    po_r: float = 1.0              # March–Dollase r（1.0 = 无择优）


@dataclass(frozen=True)
class VirtualSpec:
    """一次虚拟样合成的完整参数（即 golden 真值）。"""

    phases: tuple[PhaseSpec, ...]
    tmin: float = 5.0
    tmax: float = 90.0
    step: float = 0.02
    # 谱参数
    zero: float = 0.03             # 零点（度），实测 y(x)=f(x-zero-...)
    disp: float = 0.0             # 样品位移幅值（度），偏移 = disp·cosθ
    U: float = 0.02
    V: float = 0.0
    W: float = 0.02
    eta: float = 0.5
    X: float = 0.0                # TCH 应变项 = 4ε（度）
    Y: float = 0.0                # TCH 尺寸项 = Kλ/D（度）
    asym: float = 0.0
    bfactor: float = 0.0
    anode: str | None = "Cu"
    ka_ratio: float = 0.5
    wavelength: float = 1.5406
    integrated: bool = False      # 与 P0 bench 口径一致（峰高）
    # 背景
    bg_mode: str = "cheb"         # "cheb" | "tent"
    bg_coeffs: tuple[float, ...] = (300.0, 1.0, 0.0)
    # 噪声与强度
    noise: str = "poisson"        # "poisson" | "gaussian" | "none"
    noise_strength: float = 1.0
    target_peak: float = 50000.0
    seed: int = 20260701
    name: str = "v"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phases"] = [asdict(p) for p in self.phases]
        return d


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _profile_params(spec: VirtualSpec) -> ProfileParams:
    """构造前向模型参数（zero 置 0：位移已在求值网格上施加，避免重复）。"""
    po_r = {f"phase{i}": (p.po_hkl or (0, 0, 1), p.po_r)
            for i, p in enumerate(spec.phases)}
    po_r = {k: (v[0][0], v[0][1], v[0][2], v[1]) for k, v in po_r.items()}
    return ProfileParams(
        zero=0.0, U=spec.U, V=spec.V, W=spec.W, eta=spec.eta,
        anode=spec.anode, ka_ratio=spec.ka_ratio,
        wavelength=spec.wavelength, asym=spec.asym, bfactor=spec.bfactor,
        integrated=spec.integrated, X=spec.X, Y=spec.Y,
        po_r=None,  # PO 由下方按相名单独注入，避免把结构名与 phase{i} 混淆
    )


def synthesize(spec: VirtualSpec) -> tuple[Pattern, dict]:
    """合成一条谱，返回 ``(Pattern, truth)``。

    ``truth`` 含全部输入参数与逐相 ``Z/M/V/scale/weight_pct``，供 P1/P2
    的 round-trip 验收直接比对。
    """
    if not spec.phases:
        raise ValueError("至少需要一个物相")
    if spec.tmax <= spec.tmin or spec.step <= 0:
        raise ValueError("需满足 tmax > tmin 且 step > 0")

    grid = np.arange(spec.tmin, spec.tmax, spec.step, dtype=np.float64)
    # 实测 y(x) = f(x - zero - disp·cosθ)：直接在平移后的网格上求值，
    # 不做插值（与 bench_b.py 同一手法，避免插值误差污染真值）。
    theta = np.radians(grid / 2.0)
    eval_grid = grid - spec.zero - spec.disp * np.cos(theta)

    structs = []
    triples = []
    for p in spec.phases:
        st = parse_cif(_resolve(p.cif))
        st.name = f"phase{len(structs)}"
        z, vol, mass = qpa_inputs_from_cif(st, p.formula)
        structs.append(st)
        triples.append((z, vol, mass, p.weight_pct))

    # frac_p ∝ w_p/(Z·M·V)，归一化后作为 Rietveld 标度 S_p
    raw = np.array([w / (z * m * v) for z, v, m, w in triples], dtype=np.float64)
    if float(raw.sum()) <= 0:
        raise ValueError("质量分数全为零")
    frac = raw / raw.sum()

    prm = _profile_params(spec)
    profiles = []
    for i, st in enumerate(structs):
        p = spec.phases[i]
        this = prm
        if p.po_r != 1.0:
            from dataclasses import replace as _replace
            this = _replace(prm, po_r={st.name: (*(p.po_hkl or (0, 0, 1)), p.po_r)})
        profiles.append(compute_phase_profile(
            st, eval_grid, this, spec.tmin - 2.0, spec.tmax + 2.0))

    phase_only = np.zeros_like(grid)
    for f, prof in zip(frac, profiles):
        phase_only += f * prof

    bg = background_basis(grid, len(spec.bg_coeffs), spec.bg_mode) @ np.asarray(
        spec.bg_coeffs, dtype=np.float64)
    clean = phase_only + bg

    # 整体缩放到目标主峰高度（只缩放相贡献，背景保持不变）
    peak = float(phase_only.max())
    if peak <= 0:
        raise ValueError("相计算谱为零：检查 CIF / 波长 / 扫描窗口")
    gain = spec.target_peak / peak
    y_clean = gain * phase_only + bg
    scales = frac * gain

    rng = np.random.default_rng(spec.seed)
    if spec.noise == "poisson":
        y = rng.poisson(np.maximum(y_clean, 0.0) * spec.noise_strength).astype(
            np.float64) / spec.noise_strength
    elif spec.noise == "gaussian":
        y = y_clean + rng.normal(
            0.0, spec.noise_strength, size=y_clean.size) * np.sqrt(
                np.maximum(y_clean, 1.0))
    elif spec.noise == "none":
        y = y_clean.copy()
    else:
        raise ValueError(f"未知噪声模型: {spec.noise}")

    # 理论噪声下限 Rwp（P2.2 / §8.5 的「噪声理论 Rwp」定义）：
    # 以「完美模型 + 泊松计数」为参照，Rwp_noise = Rexp = 100·√((N−P)/Σw·y²)，
    # P 取 0 的上界估计（分母 Σw·y² 用观测谱）。
    w = 1.0 / np.maximum(y, 1.0)
    denom = float(np.sum(w * y * y))
    rwp_noise = 100.0 * np.sqrt(y.size / denom) if denom > 0 else float("nan")

    pat = Pattern(two_theta=grid, intensity=y, meta={"synthetic": True,
                                                     "seed": spec.seed})
    truth = spec.to_dict()
    truth.update({
        "n_points": int(grid.size),
        "gain": float(gain),
        "rwp_noise_theory": float(rwp_noise),
        "rwp_noise_definition": "Rexp with P=0; 100*sqrt(N/sum(w*y^2)), w=1/max(y,1)",
        "phases_detail": [
            {"name": st.name, "cif": p.cif, "weight_pct_true": p.weight_pct,
             "Z": int(z), "M": float(m), "V": float(v),
             "scale": float(s), "po_r": float(p.po_r)}
            for st, p, (z, v, m, _w), s in zip(structs, spec.phases, triples, scales)
        ],
    })
    return pat, truth


def write_dataset(specs: list[VirtualSpec], out_dir: Path) -> dict:
    """批量写 ``.xy`` + ``*_truth.json`` + ``manifest.json``。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in specs:
        pat, truth = synthesize(spec)
        stem = f"{spec.name}{spec.phases[0].weight_pct:g}"
        xy = out_dir / f"{stem}.xy"
        lines = [f"{x:10.4f}{v:12.1f}" for x, v in
                 zip(pat.two_theta, pat.intensity)]
        xy.write_text(
            f"# XinRefinement virtual (seed={spec.seed}, name={stem})\n"
            + "\n".join(lines) + "\n", encoding="utf-8")
        truth["file"] = xy.name
        (out_dir / f"{stem}_truth.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append({"stem": stem, "file": xy.name,
                        "truth": f"{stem}_truth.json",
                        "weight_pct_true": spec.phases[0].weight_pct,
                        "seed": spec.seed})
    manifest = {"generator": "tools/gen_virtual.py", "n": len(specs),
                "note": "P1-PRE 参数化虚拟样；真值见 *_truth.json",
                "samples": entries}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def tio2_preset(out_dir: Path | None = None) -> list[VirtualSpec]:
    """TiO₂ 8 配比预设（与 P0 ``bench_b.py`` 同口径，供交叉核对）。"""
    a = "xinrefinement/data/anatase.cif"
    r = "xinrefinement/data/rutile.cif"
    ratios = (0.1, 1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0)
    out = []
    for wa in ratios:
        out.append(VirtualSpec(
            phases=(PhaseSpec(cif=a, weight_pct=wa, formula="O2 Ti"),
                    PhaseSpec(cif=r, weight_pct=100.0 - wa, formula="O2 Ti")),
            name="v", seed=20260701 + int(wa * 100)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1-PRE 参数化虚拟样合成器")
    ap.add_argument("--out", default="tests/data/virtual_p1")
    ap.add_argument("--preset", choices=["tio2"], default="tio2")
    args = ap.parse_args(argv)
    out_dir = _resolve(args.out)
    specs = tio2_preset()
    m = write_dataset(specs, out_dir)
    print(f"已生成 {m['n']} 条虚拟样 → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
