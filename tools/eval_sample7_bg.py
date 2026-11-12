"""样 7 背景节点密度诊断：把 20–30° 残差里「背景形状」成分量出来。

动机
----
样 7 的加权残差 **48% 集中在 20–30°**，而我们用的是 ``bg_mode="tent"``
19 节点（5–120°，约每 6° 一个节点）——在这个窗口里只有约 2 个节点，
理论上**无法**跟随「22° 主包 + 25° 肩」这种带结构的宽包。此前 P1 试过
``bg_mode="interp", n_bg=12``（节点更稀疏）得到「更差」，那只证明
*稀疏插值*不行，**没有**回答「更密能不能行」。

为什么这是「几乎免费」的诊断
----------------------------
tent 背景的节点系数走**线性层解析求解**，不进 LM 向量。所以把 n_bg 从
19 提到 45 只增大一次线性最小二乘的规模（5751×45），**不增加任何**残差
函数评估次数，单次精修墙钟几乎不变。

口径
----
除 ``n_bg`` 外与 ``bench_v14 combo_tex_aniso`` 完全一致（5–120°、
PO 自动播种、逐相 ΔB_iso、xyz、EWIMV 织构、Popa LB、η）。因此 Rwp 差
可直接归因到背景自由度。

**注意这是诊断，不是产品建议**：加密背景会把重叠峰强度吸进本底，回归
QPA 会偏移（方石英/萤石比例尤其敏感）。若证明残差是「背景形」，正确
做法是引入物理的宽包/非晶分量，而不是发布密背景。

用法
----
    python tools/eval_sample7_bg.py                # 默认 31 / 45
    python tools/eval_sample7_bg.py --nbg 19,31,45
    python tools/eval_sample7_bg.py --report       # 只汇总已跑结果
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                              # noqa: E402
from xinrefinement.core.profile.forward import (                    # noqa: E402
    ProfileParams, aniso_default, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner           # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs            # noqa: E402

ROOT = Path(os.environ.get("XR_BENCH_ROOT", r"d:\test_XRD\ShiJK-Refinement"))
OUT = B.OUT
JSON = "m8_bg.json"
DIRS = sorted(p for p in ROOT.iterdir() if p.is_dir())


def _recipe(nbg: int, bg_mode: str = "tent", tmax: float = 120.0):
    pat, phases = B._load(7, DIRS[6], DIRS[6])
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    best: dict = {}
    for r in B._read_json("po.json"):
        if (r.get("i") == 7 and r.get("delta") is not None
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
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode=bg_mode, tmin=5.0, tmax=tmax, max_iter=40,
                       po_probe=False, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True)
    return pat, phases, prm, cfg


def _qpa(res) -> list[dict]:
    raw = [p.scale * p.volume ** 2 for p in res.phases]
    tot = sum(raw) or 1.0
    return [{"name": p.name, "vol_pct": round(100 * r / tot, 2)}
            for p, r in zip(res.phases, raw)]


def _report() -> int:
    rows = B._read_json(JSON)
    if not rows:
        print("尚无结果")
        return 0
    base = next((r["rwp_pct"] for r in rows if r.get("n_bg") == 19), None)
    print(f"{'n_bg':>5} {'bg_mode':>8} {'Rwp%':>7} {'Δ vs 19':>8} {'秒':>7}  "
          f"方石英vol%")
    for r in sorted(rows, key=lambda x: x["n_bg"]):
        if r.get("rwp_pct") is None:
            print(f"{r['n_bg']:>5} {r.get('bg_mode',''):>8}  failed")
            continue
        d = None if base is None else r["rwp_pct"] - base
        cr = next((q["vol_pct"] for q in r.get("qpa", [])
                   if "8234" in q["name"]), None)
        print(f"{r['n_bg']:>5} {r.get('bg_mode','tent'):>8} "
              f"{r['rwp_pct']:7.3f} "
              f"{('—' if d is None else f'{d:+.3f}'):>8} "
              f"{r['seconds']:7.0f}  {cr}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nbg", default="31,45")
    ap.add_argument("--bg-mode", default="tent")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        return _report()

    rows = B._read_json(JSON)
    done = {r["n_bg"] for r in rows}
    for nbg in (int(v) for v in args.nbg.split(",") if v.strip()):
        if nbg in done:
            print(f"n_bg={nbg} 已有结果，跳过", flush=True)
            continue
        pat, phases, prm, cfg = _recipe(nbg, args.bg_mode)
        t0 = time.time()
        try:
            res, recs = RecipeRunner().run_all(
                RefineInputs(pat, phases, prm, cfg))
        except Exception as exc:                                  # noqa: BLE001
            print(f"n_bg={nbg} 异常 {type(exc).__name__}: {exc}", flush=True)
            continue
        if res is None:
            print(f"n_bg={nbg} 配方无结果", flush=True)
            continue
        row = {"n_bg": nbg, "bg_mode": args.bg_mode,
               "rwp_pct": float(res.rwp),
               "seconds": round(time.time() - t0, 1),
               "qpa": _qpa(res),
               "biso": {k: round(float(v), 4)
                        for k, v in (res.params.b_iso or {}).items()},
               "steps": [(r.key, r.status,
                          None if r.rwp_after is None else round(r.rwp_after, 3),
                          r.message[:90]) for r in recs]}
        rows = [r for r in rows if r["n_bg"] != nbg] + [row]
        B._write_json(JSON, rows)
        print(json.dumps({"n_bg": nbg, "rwp_pct": row["rwp_pct"],
                          "seconds": row["seconds"]}, ensure_ascii=False),
              flush=True)
        for s in row["steps"]:
            print("   ", s[0], s[1], s[2], s[3], flush=True)
    print()
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
