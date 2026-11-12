"""IUCr 1g：ZnO 择优取向（March–Dollase）扫描。

背景：合成 round-trip 已证明引擎自洽（回收误差 ±0.1%），真实 1g 上 ZnO 却
系统性低 ~23%，且反解出的强度因子 k 在 1a/1d/1g 三个含量点上都 ≈ 0.77
（乘性、与含量无关）——这是「该相计算强度整体偏弱」的签名。择优取向是最
典型的成因（ZnO 针状/片状习性），而自动 po_probe 未通过增益阈值，故这里
手工扫描固定 r。

用法::

    python tools/eval_iucr_po_scan.py --sample 1g \
        --axes 001,100,101 --rs 1.0,0.95,0.9,0.85,0.8,0.75

输出 ``C:\\Temp\\iucr\\po_scan.json``。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xinrefinement.core.patterns import load_pattern            # noqa: E402
from xinrefinement.core.profile.cif import parse_cif            # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams    # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig    # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner       # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs        # noqa: E402

ROOT = Path(os.environ.get("XR_IUCr_ROOT", r"d:\test_XRD\IUCr_Rietveld"))
OUT = Path(r"C:/Temp/iucr")
OUT.mkdir(parents=True, exist_ok=True)

CIF = {
    "Corundum": (Path(os.environ.get("XR_BENCH_ROOT",
                    r"d:\test_XRD\ShiJK-Refinement"))
                 / "ShiJiKong3#1##20260126-130900_100"
                 / "4Entry_96-900-9673.cif"),
    "Zincite": ROOT / "Entry_96-230-0113-ZnO.cif",
    "Fluorite": ROOT / "Entry_96-230-0450-CaF2.cif",
}
TRUTH = {
    "1a": {"Corundum": 1.15, "Zincite": 4.04, "Fluorite": 94.81},
    "1d": {"Corundum": 13.53, "Zincite": 32.89, "Fluorite": 53.58},
    "1g": {"Corundum": 31.37, "Zincite": 34.21, "Fluorite": 34.42},
}
TXT = Path(r"D:\Project\XRD\XRData\IUCr\txt")


def _pattern_path(tag: str) -> Path:
    p = ROOT / f"{tag}.txt"
    return p if p.exists() else TXT / f"CPD-{tag.upper()}.txt"


def _cfg() -> RefineConfig:
    n_bg = max(6, int(round((150.0 - 5.0) / 8.0)))
    return RefineConfig(n_bg=n_bg, bg_mode="tent", tmin=5.0, tmax=150.0,
                        max_iter=40, weight_mode="sqrt")


def _match(weights: dict) -> dict:
    keys = {"Corundum": ("corund", "9673"), "Zincite": ("zno", "zinc"),
            "Fluorite": ("caf", "fluor")}
    out = {}
    for phase, wt in weights.items():
        low = phase.lower()
        for name, pats in keys.items():
            if any(p in low for p in pats):
                out[name] = wt
                break
    return out


def main(argv: list[str]) -> int:
    tag = "1g"
    axes = ("001",)
    rs = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75)
    for i, a in enumerate(argv):
        if a == "--sample" and i + 1 < len(argv):
            tag = argv[i + 1]
        if a == "--axes" and i + 1 < len(argv):
            axes = tuple(argv[i + 1].split(","))
        if a == "--rs" and i + 1 < len(argv):
            rs = tuple(float(v) for v in argv[i + 1].split(","))

    pat = load_pattern(_pattern_path(tag))
    phases = [parse_cif(CIF[n]) for n in ("Corundum", "Zincite", "Fluorite")]
    zno = next(s.name for s in phases if "zno" in s.name.lower()
               or "zinc" in s.name.lower())
    prm0 = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True)
    rows: list[dict] = []
    print(f"样品 {tag}  ZnO 相名 = {zno}")
    print(f"{'轴':>6s} {'r':>6s} {'Rwp%':>8s} "
          + "".join(f"{k:>10s}" for k in ("刚玉", "ZnO", "萤石"))
          + "   ZnO偏差   耗时")
    for ax in axes:
        hkl = tuple(int(c) for c in ax)
        for r in rs:
            t0 = time.time()
            prm = prm0 if r == 1.0 else ProfileParams(
                zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu",
                integrated=True, po_r={zno: (*hkl, float(r))})
            res, _recs = RecipeRunner().run_all(
                RefineInputs(pat, phases, prm, _cfg()))
            got = _match({p.name: float(p.weight_pct) for p in res.phases})
            err = {k: round(got[k] - TRUTH[tag][k], 2) for k in TRUTH[tag]}
            row = {"sample": tag, "axis": ax, "r": r,
                   "rwp_pct": round(float(res.rwp), 3),
                   "weights": {k: round(v, 2) for k, v in got.items()},
                   "error_pt": err,
                   "max_abs_err": max(abs(v) for v in err.values()),
                   "seconds": round(time.time() - t0, 1)}
            rows.append(row)
            (OUT / "po_scan.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"{ax:>6s} {r:>6.2f} {row['rwp_pct']:8.3f} "
                  + "".join(f"{got[k]:10.2f}" for k in
                            ("Corundum", "Zincite", "Fluorite"))
                  + f"  {err['Zincite']:+8.2f} {row['seconds']:6.1f}s",
                  flush=True)
    print("\n对照：r=1.00 即无择优取向（基线）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
