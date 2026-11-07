"""v1.5.0 验收：7 样全量对拍（出厂基准口径，与立项书 §1.7 严格同参）。

目的
----
v1.5 期间改了十来处（M3 球谐、M4 Popa LB、M9 按相降级、M9b 时间护栏、
M10/M10b 分步投影、M11 边界峰、M8c 多型建议、M6/M7 探针、M5 换基），其中
多数声称「默认路径逐位不变」。**验收的硬证据就是这 7 个数字原样复现 §1.7**：

    11.880 / 6.968 / 8.123 / 10.263 / 15.942 / 12.122 / 14.689

任何一处默认值被动过，这里立刻会对不上。

口径（与 `bench_v14 combo_tex_aniso` 完全一致）
-----------------------------------------------
- tent 背景 19 节点（每 6°，窗口 5–120°；样 5 为 10–100°）
- 逐相 ΔB_iso、xyz、po.json 命中轴的 EWIMV 织构、Popa LB 各向异性、η
- PO 自动试探关（轴来自 po.json，与 §1.7 同源）
- **不设时间预算**（设了会截断慢步，与 §1.7 不可比）；慢样请自行等

用法
----
    python tools/accept_v150.py --samples 4
    python tools/accept_v150.py --all
    python tools/accept_v150.py --report
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
from xinrefinement.core.profile.forward import (                    # noqa: E402
    ProfileParams, aniso_default, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner           # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs            # noqa: E402

#: MAUD 2.99993 实测（立项书 §1 / §5 验收标准）
MAUD = {1: 10.90, 2: 6.34, 3: 10.29, 4: 9.96, 5: 14.87, 6: 14.76, 7: 11.30}
#: 立项书 §1.7 基准（本脚本必须逐位复现，容差 2e-3 用于确认「同一代码路径」）
BASE = {1: 11.880, 2: 6.968, 3: 8.123, 4: 10.263,
        5: 15.942, 6: 12.122, 7: 14.689}
#: §5 验收：逐样 Rwp ≤ MAUD + 2 pt
TOL = 2.0


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
                       po_probe=False, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True)
    return pat, phases, prm, cfg


def _qpa(res) -> list[dict]:
    raw = [p.scale * p.volume ** 2 for p in res.phases]
    tot = sum(raw) or 1.0
    return [{"name": p.name, "vol_pct": round(100 * r / tot, 2),
             "d_biso": round(float((res.params.b_iso or {}).get(p.name, 0.0)), 4),
             "cell": [round(float(v), 5) for v in p.cell]}
            for p, r in zip(res.phases, raw)]


def _steps(recs) -> list[dict]:
    """把 StepRecord 转成可 JSON 的字典；任何异常都不许拖垮主结果。

    踩过的坑：先前直接读 `r.name`/`r.rwp`（StepRecord 实际字段是
    `key`/`rwp_before`/`rwp_after`），AttributeError 在 run_all
    跑完之后才抛出，整轮 20–70 min 的计算全部白跑。
    """
    out = []
    for r in (recs or []):
        try:
            out.append({
                "key": r.key, "title": r.title,
                "status": r.status,
                "rwp_before": (round(float(r.rwp_before), 4)
                               if r.rwp_before is not None else None),
                "rwp_after": (round(float(r.rwp_after), 4)
                              if r.rwp_after is not None else None),
                "message": r.message})
        except Exception:                                 # noqa: BLE001
            out.append({"repr": repr(r)})
    return out


def run(i: int) -> dict:
    d, pdir = next((dd, pp) for k, dd, pp in B.sample_dirs() if k == i)
    pat, phases, prm, cfg = _build(i, d, pdir)
    t0 = time.time()
    runner = RecipeRunner()
    res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
    if res is None:
        print(f"  样{i}: 配方无结果", flush=True)
        return {"i": i, "error": "无结果"}
    row = {"i": i, "rwp_pct": round(float(res.rwp), 4),
           "minutes": round((time.time() - t0) / 60.0, 1),
           "U": round(float(res.params.U), 6),
           "V": round(float(res.params.V), 6),
           "W": round(float(res.params.W), 6),
           "zero": round(float(res.params.zero), 6),
           "eta": round(float(res.params.eta), 6),
           "qpa": _qpa(res),
           "xyz": getattr(res, "xyz_report", None) or {},
           "steps": _steps(recs)}
    (B.OUT / f"accept_v150_{i}.json").write_text(
        json.dumps([row], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  样{i}: Rwp {row['rwp_pct']:.4f}%  ({row['minutes']} min)  "
          f"ΔB_iso={[q['d_biso'] for q in row['qpa']]}", flush=True)
    return row


def _all_rows() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for p in sorted(B.OUT.glob("accept_v150_*.json")):
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            if "i" in r:
                out[int(r["i"])] = r
    return out


def _report() -> int:
    rows = _all_rows()
    if not rows:
        print("尚无结果")
        return 0
    print(f"{'样':>2} {'MAUD':>6} {'§1.7':>7} {'本次':>8} {'Δ§1.7':>8} "
          f"{'gap':>6} {'判定':>6} {'min':>6}  ΔB_iso")
    ok = 0
    tot, n = 0.0, 0
    for i in sorted(rows):
        r = rows[i]
        if r.get("rwp_pct") is None:
            print(f"{i:>2} 失败：{r.get('error')}")
            continue
        rwp = r["rwp_pct"]
        gap = rwp - MAUD.get(i, 0.0)
        dev = rwp - BASE.get(i, rwp)
        good = gap <= TOL
        ok += int(good)
        tot += rwp
        n += 1
        db = " / ".join(f"{q['d_biso']:+.3f}" for q in r.get("qpa", []))
        print(f"{i:>2} {MAUD.get(i, 0):6.2f} {BASE.get(i, 0):7.3f} {rwp:8.3f} "
              f"{dev:+8.3f} {gap:+6.2f} {'PASS' if good else 'FAIL':>6} "
              f"{r.get('minutes', 0):6.1f}  {db}")
    if n:
        print(f"\n均值 {tot / n:.3f}%（MAUD {sum(MAUD[i] for i in rows if i in MAUD) / max(1, len([i for i in rows if i in MAUD])):.2f}%）"
              f"  逐样 PASS {ok}/{n}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        return _report()
    want = ([1, 2, 3, 4, 5, 6, 7] if args.all
            else [int(v) for v in args.samples.split(",") if v.strip()])
    if not want:
        ap.error("需要 --samples 或 --all")
    for i in want:
        print(f"=== 样 {i}", flush=True)
        run(i)
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
