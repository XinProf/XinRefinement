"""P4.2 · 虚拟样 round-trip 全基准（多晶系 × 多相）。

用 P1-PRE 的 ``gen_virtual`` 参数化合成器生成已知真值谱，再逐条
精修回收，输出 Markdown 报告 + JSON 明细。

判据（plan §8.5）：``Rwp ≤ 1.10·Rexp 且 χ² ≤ 1.21`` 为严格档；
质量分数回收误差 < 0.5pp。

运行::

    D:/Project/XRD/python310/python.exe tools/bench_full.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gen_virtual import PhaseSpec, VirtualSpec, synthesize  # noqa: E402

from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams  # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig  # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve  # noqa: E402

A = "xinrefinement/data/anatase.cif"
R = "xinrefinement/data/rutile.cif"
OUT = ROOT / "tests" / "out"


def _cases():
    """8 配比 × 2 个背景模式，另加 3 个尺寸/应变档。"""
    cases = []
    for wa in (0.1, 1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0):
        for bg_mode in ("cheb", "tent"):
            cases.append((f"w{wa:g}_{bg_mode}", VirtualSpec(
                phases=(PhaseSpec(cif=A, weight_pct=wa, formula="O2 Ti"),
                        PhaseSpec(cif=R, weight_pct=100.0 - wa,
                                  formula="O2 Ti")),
                bg_mode=bg_mode,
                bg_coeffs=((300.0, 120.0, 80.0, 200.0)
                           if bg_mode == "tent" else (300.0, 20.0, 5.0)),
                seed=20260701 + int(wa * 100))))
    for Y in (0.05, 0.15):
        cases.append((f"size_Y{Y:g}", VirtualSpec(
            phases=(PhaseSpec(cif=A, weight_pct=50.0, formula="O2 Ti"),
                    PhaseSpec(cif=R, weight_pct=50.0, formula="O2 Ti")),
            Y=Y, seed=424242)))
    return cases


def run() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    phases = [parse_cif(ROOT / A), parse_cif(ROOT / R)]
    rows = []
    for name, spec in _cases():
        pat, truth = synthesize(spec)
        prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                            anode="Cu", integrated=False)
        # 合成时启用了尺寸/应变项，精修必须同步放开对应开关，
        # 否则是「模型欠拟合」而非算法缺陷（基准口径须自洽）。
        cfg = RefineConfig(refine_zero=True, refine_uvw=True,
                           refine_size=(spec.Y > 0.0),
                           refine_strain=(spec.X > 0.0),
                           n_bg=len(spec.bg_coeffs), bg_mode=spec.bg_mode,
                           tmin=spec.tmin, tmax=spec.tmax, max_iter=60)
        res = solve(RefineInputs(
            pattern=pat, phases=phases, profile=prm, config=cfg,
            formulas={"anatase": "O2 Ti", "rutile": "O2 Ti"}))
        wa_true = spec.phases[0].weight_pct
        wa_rec = res.phases[0].weight_pct
        delta = (None if wa_rec is None else wa_rec - wa_true)
        strict = (res.rwp <= 1.10 * res.rexp and res.chi2 <= 1.21)
        ok = (res.success and strict and delta is not None
              and abs(delta) < 0.5)
        rows.append({"case": name, "wa_true": wa_true, "wa_rec": wa_rec,
                     "delta": delta, "rwp": res.rwp, "rexp": res.rexp,
                     "chi2": res.chi2, "strict": strict, "ok": bool(ok),
                     "rwp_noise_theory": truth["rwp_noise_theory"]})
    return rows


def main() -> int:
    rows = run()
    (OUT / "bench_full.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 虚拟样 round-trip 全基准（tools/bench_full.py）", "",
             "| 用例 | wa 真值% | 回收% | Δ | Rwp% | Rexp% | χ² | 严格档 | 判定 |",
             "|---|---:|---:|---:|---:|---:|---:|:---:|:---:|"]
    for r in rows:
        rec = "—" if r["wa_rec"] is None else f"{r['wa_rec']:.3f}"
        delta = "—" if r["delta"] is None else f"{r['delta']:+.3f}"
        strict = "PASS" if r["strict"] else "—"
        verdict = "PASS" if r["ok"] else "FAIL"
        lines.append(
            f"| {r['case']} | {r['wa_true']:g} | {rec} | {delta} | "
            f"{r['rwp']:.2f} | {r['rexp']:.2f} | {r['chi2']:.2f} | "
            f"{strict} | {verdict} |")
    n_ok = sum(r["ok"] for r in rows)
    lines += ["", f"**总判定: {n_ok}/{len(rows)} PASS**", ""]
    report = "\n".join(lines)
    (ROOT / "bench_full_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
