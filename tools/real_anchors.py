"""P2.11 · 真实数据锚点登记（在 xinrefinement.core 上跑通家族实样）。

目的不是"刷低 Rwp"，而是**如实登记**：同一实样在本项目引擎上的
Rwp / 收敛 / 物相含量，供后续与家族基线、外部软件交叉验证对照。

口径说明
--------
- 真实谱的峰形/背景/择优取向模型与虚拟样不同，Rwp 不能用虚拟样的
  严格档（Rwp ≤ 1.10·Rexp）判定；只做「能收敛 + 数值合理」登记。
- 外部软件（GSAS-II/FullProf/MAUD/Profex）的 Rwp 因背景/峰形/权重实现
  不同，按 plan §8.4 **只比结构量**（晶胞、含量、占位、R_Bragg），
  Rwp 仅登记不硬比。

运行::

    D:/Project/XRD/python310/python.exe tools/real_anchors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xinrefinement.core.patterns import load_pattern  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams  # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig  # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve  # noqa: E402

NCM811 = Path("D:/Project/XRD/XRData/csuHJW/txt/Data040：NCM：811_raw.txt")
ANCHORS = (
    {"name": "TiO2_virtual_b_v50", "pattern": ROOT / "tests/data/virtual_b/v50_wide.xy",
     "cifs": [ROOT / "xinrefinement/data/anatase.cif",
              ROOT / "xinrefinement/data/rutile.cif"],
     "note": "家族 RutAna B 法虚拟样，golden 锚点"},
    {"name": "NCM811_real", "pattern": NCM811,
     "cifs": [ROOT / "xinrefinement/data/cif/NCA_80_15_05.cif"],
     "note": "NCA 家族三元层状正极实样（同构锚点）"},
)


def run_one(case: dict) -> dict:
    if not Path(case["pattern"]).exists():
        return {"name": case["name"], "status": "missing",
                "note": case["note"]}
    pat = load_pattern(case["pattern"])
    phases = [parse_cif(p) for p in case["cifs"]]
    tmax = min(90.0, float(pat.two_theta[-1]))
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_po=True,
                       n_bg=6, bg_mode="cheb", backend="scipy",
                       tmin=float(pat.two_theta[0]), tmax=tmax, max_iter=60)
    res = solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                             config=cfg))
    return {
        "name": case["name"], "status": "ok", "note": case["note"],
        "n_points": int(pat.two_theta.size),
        "window": [float(pat.two_theta[0]), tmax],
        "rwp": res.rwp, "rp": res.rp, "rexp": res.rexp, "chi2": res.chi2,
        "success": res.success, "iters": res.iters,
        "phases": [{"name": p.name, "weight_pct": p.weight_pct,
                    "cell": list(p.cell)} for p in res.phases],
        "warnings": list(res.warnings),
    }


def main() -> int:
    rows = [run_one(c) for c in ANCHORS]
    out = ROOT / "tests" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "real_anchors.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 真实数据锚点登记（tools/real_anchors.py）", "",
             "| 锚点 | 点数 | Rwp% | Rp% | Rexp% | χ² | 收敛 | 说明 |",
             "|---|---:|---:|---:|---:|---:|:---:|---|"]
    for r in rows:
        if r["status"] != "ok":
            lines.append(f"| {r['name']} | — | — | — | — | — | — | 数据缺失 |")
            continue
        lines.append(
            f"| {r['name']} | {r['n_points']} | {r['rwp']:.2f} | "
            f"{r['rp']:.2f} | {r['rexp']:.2f} | {r['chi2']:.2f} | "
            f"{r['success']} | {r['note']} |")
    lines += ["", "> Rwp 仅登记不硬比；结构量（晶胞/含量/占位）才与外部软件对照。", ""]
    report = "\n".join(lines)
    (ROOT / "docs/REAL_ANCHORS.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
