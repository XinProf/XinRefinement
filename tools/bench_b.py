"""T4.6 · B 法 round-trip 验收 bench（含 tests/data/virtual_b 虚拟样生成）。

数据策略（team-lead 指定）：若 A 组的 tests/data/virtual/manifest.json 尚不存在，
本脚本用 PolyXRD-SynthPattern 的 synthesize_multi_phase 在 tests/data/virtual_b/
下自行生成同一套 8 配比（0.1/1/5/25/50/75/95/99 %）数据自用，seed=20260701。

物理标度（关键！）：SynthPattern 的多相叠加用 scale ∝ frac/V，而 Rietveld 的
Hill–Howard 定量公式要求强度 ∝ w/(Z·M·V)。故生成时把质量分数换算成
frac_p ∝ w_p/(Z_p·M_p) 再传入，使 truth（质量分数）与 QPA 公式自洽。
锐钛型 Z=4、金红石型 Z=2（同化学式 TiO2，M 相同），若不做该换算，
round-trip 会差出 Z 倍 —— 详见 docs/CIF_SOURCE.md 调试日志。

噪声模型：用泊松计数噪声（strength=1.0）而非 SynthPattern 缺省的 0.3%·Imax
常数噪声。原因：Rietveld 权重按计数统计 w=1/y，常数强噪声在计数统计权重下
会使 Rwp 虚高到 ~30%（违反标准 Rwp≤10% 判据的统计前提）；泊松噪声与权重
模型自洽，Rwp ≈ 4%。同样记录在调试日志。

运行: D:/Project/XRD/python310/python.exe tools/bench_b.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xinrefinement.core.dtypes import Pattern  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import (  # noqa: E402
    ProfileParams,
    caglioti_2theta,
)
from xinrefinement.core.refine.nonlinear import RefineConfig, refine  # noqa: E402
from xinrefinement.core.refine.qpa import (  # noqa: E402
    qpa_inputs_from_cif,
    qpa_weights,
    to_ratio,
)

SEED = 20260701
SYNTH_DIR = Path(r"D:/Project/XRD/PolyXRD-SynthPattern")
RATIOS = [0.1, 1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0]
# 虚拟样 profile（与 rutana 前向模型同一参数化，truth 冻结进 manifest）
PROFILE = {"tmin": 5.0, "tmax": 90.0, "step": 0.02, "U": 0.02, "V": 0.0,
           "W": 0.02, "eta": 0.5, "zero": 0.03, "anode": "Cu",
           "ka_ratio": 0.5, "noise": "poisson", "target_peak": 50000.0,
           "bg": [300.0, 1.0, 0.0]}
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"
GOLDEN = ROOT / "tests" / "golden" / "method_b_roundtrip.json"
OUT_DIR = ROOT / "tests" / "out"


def _synth_engine():
    """加载 SynthPattern 合成引擎（仅 tools 脚本允许跨仓引用）。"""
    sys.path.insert(0, str(SYNTH_DIR))
    import xrd_synth_engine  # noqa: PLC0415
    return xrd_synth_engine


def load_builtin_structs() -> tuple:
    """内置两相 CifStructure（rutana/data/*.cif）。"""
    st_a = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    st_r = parse_cif(ROOT / "xinrefinement" / "data" / "rutile.cif")
    return st_a, st_r


def ensure_virtual_b() -> dict:
    """确保 tests/data/virtual_b 存在（8 配比宽扫谱 + manifest），返回 manifest。"""
    manifest_path = VIRTUAL_B / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    xse = _synth_engine()
    st_a, st_r = load_builtin_structs()
    za, va, ma = qpa_inputs_from_cif(st_a, "O2 Ti")
    zr, vr, mr = qpa_inputs_from_cif(st_r, "O2 Ti")
    grid = xse.make_grid(PROFILE["tmin"], PROFILE["tmax"] - PROFILE["step"],
                         PROFILE["step"])
    VIRTUAL_B.mkdir(parents=True, exist_ok=True)
    entries = []
    for wa in RATIOS:
        wr = 100.0 - wa
        # 物理标度换算: 生成器内部 scale = frac/V，物理要求 scale ∝ w/(Z·M·V)，
        # 故 frac ∝ w/(Z·M)（不要再除 V —— 除两次会差出 V_r/V_a ≈ 0.457 的系统偏差）
        fa = wa / (za * ma)
        fr = wr / (zr * mr)
        norm = fa + fr
        specs = [(st_a, fa / norm), (st_r, fr / norm)]
        # FWHM 用 rutana 修正口径 caglioti_2theta（tanθ，θ=2θ/2）：xse 自带的
        # caglioti 以 tan(2θ) 求值（家族历史语义，物理有误，2θ>90° 后失真）。
        # 生成端与拟合端必须同一口径 —— v1.0.0 实证记录于 docs/VALIDATION_v1.0.0.md。
        fwhm = caglioti_2theta(PROFILE["U"], PROFILE["V"], PROFILE["W"])
        physics = {"anode": PROFILE["anode"], "ka_ratio": PROFILE["ka_ratio"]}
        # 零点偏移: 实测 y(x) = f(x − zero)。直接在 (grid − zero) 上合成，无插值误差
        shifted, _info = xse.synthesize_multi_phase(
            specs, grid - PROFILE["zero"],
            wavelength=1.5406, fwhm_func=fwhm,
            eta=PROFILE["eta"], bg=tuple(PROFILE["bg"]),
            noise_strength=1.0, noise_floor=0.0,
            target_peak=PROFILE["target_peak"], noise_rel=0.0,
            seed=SEED, physics=physics)
        y = np.asarray(shifted, dtype=float)
        stem = f"v{wa:g}_wide"
        lines = [f"{x:10.4f}{v:12.1f}" for x, v in zip(grid, y)]
        (VIRTUAL_B / f"{stem}.xy").write_text(
            "# PolyXRD-RutAna virtual_b (seed=%d)\n" % SEED
            + "\n".join(lines) + "\n", encoding="utf-8")
        truth = {"wa_nominal": wa, "wr_nominal": wr, "profile": PROFILE,
                 "file": f"{stem}.xy", "seed": SEED}
        (VIRTUAL_B / f"{stem}_truth.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append(truth)
    manifest = {"seed": SEED, "n_ratios": len(RATIOS),
                "samples": entries, "note": "B 法自用虚拟样（物理标度见脚本头）"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return manifest


def _load_pattern(path: Path) -> Pattern:
    """读两列 .xy（本脚本自产数据，格式固定）。"""
    xs, ys = [], []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        xs.append(float(parts[0]))
        ys.append(float(parts[1]))
    return Pattern(two_theta=np.array(xs), intensity=np.array(ys),
                   meta={"path": str(path)})


def run_roundtrip(verbose: bool = True) -> list[dict]:
    """8 配比 round-trip：合成 -> refine -> qpa -> to_ratio -> 与 truth 比对。"""
    ensure_virtual_b()
    st_a, st_r = load_builtin_structs()
    za, va, ma = qpa_inputs_from_cif(st_a, "O2 Ti")
    zr, vr, mr = qpa_inputs_from_cif(st_r, "O2 Ti")
    rows = []
    for truth in json.loads(
            (VIRTUAL_B / "manifest.json").read_text(encoding="utf-8"))["samples"]:
        pat = _load_pattern(VIRTUAL_B / truth["file"])
        prm0 = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                             anode="Cu", integrated=False)  # 合成数据=峰高口径
        cfg = RefineConfig(refine_zero=True, refine_uvw=True,
                           refine_eta=False, n_bg=3, max_iter=40,
                           tmin=PROFILE["tmin"], tmax=PROFILE["tmax"])
        res = refine([st_a, st_r], pat, prm0, cfg)
        ws = qpa_weights([(st_a.name, res.scales[0], za, va, ma),
                          (st_r.name, res.scales[1], zr, vr, mr)])
        wa_rec, wr_rec = to_ratio(ws, 0, 1)
        wa_true = truth["wa_nominal"]
        delta = wa_rec - wa_true
        if wa_true >= 95.0:
            ok = abs(delta) <= 0.30
        else:
            ok = abs(delta) <= max(0.5, 0.02 * wa_true)
        rows.append({"wa_true": wa_true, "wa_rec": wa_rec, "wr_rec": wr_rec,
                     "delta": delta, "rwp": res.rf.rwp, "ok": bool(ok),
                     "success": bool(res.success),
                     "zero": res.params.zero, "U": res.params.U,
                     "V": res.params.V, "W": res.params.W,
                     "history": res.history,
                     "ycalc": res.ycalc.tolist()})
        if verbose:
            print(f"wa={wa_true:6.2f}%  rec={wa_rec:7.3f}%  Δ={delta:+.3f}  "
                  f"Rwp={res.rf.rwp:5.2f}%  zero={res.params.zero:+.4f}  "
                  f"W={res.params.W:.5f}  ok={ok}")
        _plot_fit(pat, res, wa_true)
    return rows


def _plot_fit(pat: Pattern, res, wa_true: float) -> None:
    """单配比拟合图（obs/calc/diff），存 tests/out。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(pat.two_theta, pat.intensity, ".", ms=1.5, color="#444",
             label="obs")
    ax1.plot(pat.two_theta, res.ycalc, "-", lw=0.8, color="C3", label="calc")
    ax1.set_ylabel("intensity")
    ax1.legend(loc="upper right")
    ax1.set_title(f"virtual_b v{wa_true:g}%  Rwp={res.rf.rwp:.2f}%")
    ax2.plot(pat.two_theta, pat.intensity - res.ycalc, ".", ms=1.5, color="#444")
    ax2.axhline(0.0, color="C3", lw=0.8)
    ax2.set_xlabel("2θ (deg)")
    ax2.set_ylabel("diff")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"fit_v{wa_true:g}.png", dpi=120)
    plt.close(fig)


def judge(rows: list[dict]) -> bool:
    """判据：全部 Rwp≤10%（标准硬条款）+ 回收误差在限内。"""
    return all(r["ok"] and r["rwp"] <= 10.0 for r in rows)


def freeze_golden(rows: list[dict]) -> None:
    """冻结 golden 基线（不含逐点数组，只含结果量）。"""
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items()
             if k not in ("history", "ycalc")} for r in rows]
    GOLDEN.write_text(json.dumps(slim, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def main() -> int:
    rows = run_roundtrip()
    all_ok = judge(rows)
    freeze_golden(rows)
    lines = ["# B 法 round-trip 验收报告（tools/bench_b.py）", "",
             "| wa 真值 % | wa 回收 % | Δ | Rwp % | 判定 |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['wa_true']:g} | {r['wa_rec']:.3f} "
                     f"| {r['delta']:+.3f} | {r['rwp']:.2f} "
                     f"| {'PASS' if r['ok'] and r['rwp'] <= 10 else 'FAIL'} |")
    lines += ["", f"**总判定: {'ALL PASS' if all_ok else 'FAIL'}**", ""]
    report = "\n".join(lines)
    (ROOT / "bench_report_b.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
