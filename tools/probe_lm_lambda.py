"""M7 探针：LM 初始阻尼 λ 到底值不值（对齐 MAUD 的 λ=0.01）。

做法
----
对每个样，从**原始起点**（U=V=0、W=0.02、无背景）做一次**联合**精修
（zero + U/V/W + η + asym + 晶胞 + tent 背景，即配方 profile 步的模型），
只改 ``lm_lambda0``。联合精修是分步投影陷阱最容易暴露的地方（M10 就是
在这里卡住的），因此也是 λ 唯一可能改变结局的地方。

判据：若 λ=0.01 在多数样上不差于 λ=1e-3 且至少一个样明显更好，就值得
把它做成可比选项；若普遍更差，M7 直接判负、保留 1e-3。

用法::

    python tools/probe_lm_lambda.py --samples 1,3,5,7
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                              # noqa: E402
from xinrefinement.core.profile.forward import (                   # noqa: E402
    ProfileParams, aniso_default, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve     # noqa: E402

LAMBDAS = (1e-3, 3e-3, 1e-2)


def _window(i: int) -> tuple[float, float]:
    return (10.0, 100.0) if i == 5 else (5.0, 120.0)


def _build(i: int, d: Path, pdir: Path):
    pat, phases = B._load(i, d, pdir)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    best: dict = {}
    for r in B._read_json("po.json"):
        if (r.get("i") == i and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v) for v in r["axis"])
            if ph not in best or r["delta"] < best[ph][1]:
                best[ph] = (ax, r["delta"])
    if best:
        prm = replace(prm, texture={
            ph: {"axis": ax, "grid": default_texture_grid()}
            for ph, (ax, _d) in best.items()})
    prm = replace(prm, aniso={st.name: aniso_default(1.5406, 0.0, 0.05)
                              for st in phases})
    tmin, tmax = _window(i)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=19,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40,
                       refine_eta=True, refine_asym=True, refine_cell=True,
                       po_probe=False, refine_biso=False, refine_xyz=False,
                       refine_aniso=False, refine_texture=False,
                       # 已配好的 aniso/织构照旧**施加**（不精修）
                       )
    return pat, phases, prm, cfg


def _qpa(res) -> list[dict]:
    raw = [p.scale * p.volume ** 2 for p in res.phases]
    tot = sum(raw) or 1.0
    return [{"name": p.name, "vol_pct": round(100 * r / tot, 2)}
            for r, p in zip(raw, res.phases)]


def run(i: int) -> dict:
    d, pdir = next((dd, pp) for k, dd, pp in B.sample_dirs() if k == i)
    pat, phases, prm, cfg = _build(i, d, pdir)
    rows = []
    for lam in LAMBDAS:
        t0 = time.time()
        res = solve(RefineInputs(pat, phases, prm, replace(cfg,
                                                           lm_lambda0=lam)))
        rows.append({"lambda0": lam, "rwp": round(float(res.rwp), 4),
                     "seconds": round(time.time() - t0, 1),
                     "restarted": bool(getattr(res, "restarted", False)),
                     "qpa": _qpa(res)})
        print(f"  样{i} λ={lam:g} → {res.rwp:.4f}% "
              f"({rows[-1]['seconds']:.0f}s)", flush=True)
    base = rows[0]["rwp"]
    for r in rows:
        r["delta"] = round(r["rwp"] - base, 4)
    return {"i": i, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="1,3,5,7")
    ap.add_argument("--out", default="m7_lm_lambda.json")
    args = ap.parse_args(argv)
    want = [int(v) for v in args.samples.split(",") if v.strip()]
    out = []
    for i in want:
        print(f"=== 样 {i}", flush=True)
        out.append(run(i))
        print(json.dumps(out[-1], ensure_ascii=False), flush=True)
        (B.OUT / args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 汇总（Δ 相对 λ=1e-3）===")
    print(f"{'样':>2} " + " ".join(f"{f'λ={l:g}':>10}" for l in LAMBDAS)
          + f" {'最佳':>6}")
    for r in out:
        cells = " ".join(f"{x['rwp']:10.4f}" for x in r["rows"])
        best = min(r["rows"], key=lambda x: x["rwp"])
        print(f"{r['i']:>2} {cells} {best['lambda0']:>6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
