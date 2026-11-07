"""M5（P4）峰形角依赖基：tanθ 基 vs 1/d 基，全样对照。

为什么要做
----------
tanθ 基 ``FWHM² = U·tan²θ + V·tanθ + W`` 在 2θ→180° 时发散。§1.5 实测纯刚玉
精修出 U=0.188，FWHM 从低角 0.195° 一路涨到 100° 的 ~0.85°，而 GSAS-II 全程
~0.11°——高角过宽是我们峰形模型最明确的系统性嫌疑。``x = 1/d = 2sinθ/λ`` 在
2θ→180° **饱和于 2/λ**，不会爆；这正是 MAUD ``_riet_caglioti_d_dep`` 一族
参数化的动机。

实验设计（干净 A/B）
--------------------
两臂**起点完全相同**：``U=V=0, W=0.02`` 是常数宽度，换基后精确等于
``(0, 0, 0.02)``（见 ``tests/test_width_basis.py`` 的恒等断言）。所以两臂
唯一的差别就是精修时 U/V/W 所乘的角函数——差异只能归因到基。

其余口径与 ``bench_v14 combo_tex_aniso`` 完全一致：PO 探索关、逐相 ΔB_iso、
xyz、po.json 命中轴的织构、Popa LB、η、tent 19 节点；窗口 5–120°，样 5 为
10–100°。

用法
----
    python tools/eval_width_basis.py --samples 1
    python tools/eval_width_basis.py --samples 1,5,7 --bases tan,d
    python tools/eval_width_basis.py --report
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
    ProfileParams, aniso_default, convert_width_basis, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner           # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs            # noqa: E402

#: MAUD 实测（立项书 §1.7 表）
MAUD = {1: 10.90, 2: 6.34, 3: 10.29, 4: 9.96, 5: 14.87, 6: 14.76, 7: 11.30}
#: 立项书 §1.7 的 combo_tex_aniso 基准（tan 基），用于校验本脚本保真
BASE = {1: 11.880, 2: 6.968, 3: 8.123, 4: 10.263,
        5: 15.942, 6: 12.122, 7: 14.689}


def _window(i: int) -> tuple[float, float]:
    return (10.0, 100.0) if i == 5 else (5.0, 120.0)


def _row_file(i: int, basis: str) -> str:
    """每（样, 基）一个文件。

    共用 JSON 会「读—改—写」互相覆盖（M8d 踩过这个坑）；这里进一步按基
    拆开，才能让 tan/d 两臂**并行**跑同一样。
    """
    return f"m5_wb_{i}_{basis}.json"


def _build(i: int, d: Path, pdir: Path, basis: str):
    pat, phases = B._load(i, d, pdir)
    tmin, tmax = _window(i)
    # 常宽度起点；换基后 (0,0,0.02) 精确不变，故两臂起点是**同一条曲线**
    u, v, w = 0.0, 0.0, 0.02
    if basis == "d":
        u, v, w = convert_width_basis(0.0, 0.0, 0.02, 1.5406, tmin, tmax,
                                      frm="tan", to="d")
    prm = ProfileParams(zero=0.0, U=u, V=v, W=w, eta=0.5,
                        anode="Cu", integrated=True, width_basis=basis)
    best: dict = {}
    for r in B._read_json("po.json"):
        if (r.get("i") == i and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v_) for v_ in r["axis"])
            if ph not in best or r["delta"] < best[ph][1]:
                best[ph] = (ax, r["delta"])
    if best:
        prm = replace(prm, texture={
            ph: {"axis": ax, "grid": default_texture_grid()}
            for ph, (ax, _d) in best.items()})
    prm = replace(prm, aniso={st.name: aniso_default(1.5406, 0.0, 0.05)
                              for st in phases})
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=19,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40,
                       po_probe=False, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True)
    return pat, phases, prm, cfg


def _qpa(res) -> list[dict]:
    raw = [p.scale * p.volume ** 2 for p in res.phases]
    tot = sum(raw) or 1.0
    return [{"name": p.name, "vol_pct": round(100 * r / tot, 2)}
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


def run(i: int, bases: tuple[str, ...]) -> list[dict]:
    d, pdir = next((dd, pp) for k, dd, pp in B.sample_dirs() if k == i)
    out = []
    for basis in bases:
        pat, phases, prm, cfg = _build(i, d, pdir, basis)
        t0 = time.time()
        runner = RecipeRunner()
        res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
        if res is None:
            print(f"  样{i} {basis}: 配方无结果", flush=True)
            out.append({"i": i, "basis": basis, "error": "无结果"})
            continue
        row = {"i": i, "basis": basis,
               "rwp_pct": round(float(res.rwp), 4),
               "minutes": round((time.time() - t0) / 60.0, 1),
               "U": round(float(res.params.U), 6),
               "V": round(float(res.params.V), 6),
               "W": round(float(res.params.W), 6),
               "qpa": _qpa(res),
               "xyz": getattr(res, "xyz_report", None) or {},
               "steps": _steps(recs)}
        out.append(row)
        print(f"  样{i} {basis}: Rwp {row['rwp_pct']:.4f}%  "
              f"({row['minutes']} min)  U={row['U']:+.5f} V={row['V']:+.5f} "
              f"W={row['W']:.5f}", flush=True)
        (B.OUT / _row_file(i, basis)).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _all_rows() -> dict[tuple[int, str], dict]:
    out: dict[tuple[int, str], dict] = {}
    for p in sorted(B.OUT.glob("m5_wb_*.json")):
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            if "i" in r and "basis" in r:
                out[(int(r["i"]), r["basis"])] = r
    return out


def _report() -> int:
    rows = _all_rows()
    if not rows:
        print("尚无结果")
        return 0
    by: dict[int, dict[str, dict]] = {}
    for (i, b), r in rows.items():
        by.setdefault(i, {})[b] = r
    print(f"{'样':>2} {'MAUD':>6} {'§1.7 tan':>9} {'tan':>8} {'d':>8} "
          f"{'Δ(d−tan)':>9} {'gap@d':>7}  {'max|Δvol%|':>18}")
    for i in sorted(by):
        t = by[i].get("tan") or {}
        dd = by[i].get("d") or {}
        tp, dp = t.get("rwp_pct"), dd.get("rwp_pct")
        ref = f"{BASE[i]:9.3f}" if i in BASE else f"{'—':>9}"
        cells = f"{tp:8.3f}" if tp is not None else f"{'—':>8}"
        cells += f" {dp:8.3f}" if dp is not None else f" {'—':>8}"
        delta = (f"{dp - tp:+9.3f}"
                 if (tp is not None and dp is not None) else f"{'—':>9}")
        gap = (f"{dp - MAUD[i]:+7.2f}"
               if (dp is not None and i in MAUD) else f"{'—':>7}")
        qa = {q["name"]: q["vol_pct"] for q in (t.get("qpa") or [])}
        qb = {q["name"]: q["vol_pct"] for q in (dd.get("qpa") or [])}
        worst, who = 0.0, "—"
        for name in set(qa) & set(qb):
            e = abs(qb[name] - qa[name])
            if e > worst:
                worst, who = e, name.split()[-1]
        tag = f"{worst:6.2f} ({who})" if who != "—" else "—"
        print(f"{i:>2} {MAUD.get(i, 0):6.2f} {ref} {cells} {delta} {gap}  "
              f"{tag:>18}")
    print("\n（tan = v1.5 出厂口径，应逐位复现 §1.7 基准；"
          "Δ 为 d 基相对 tan 基的 Rwp 变化，负数 = d 基更好）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="1")
    ap.add_argument("--bases", default="tan,d")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        return _report()
    bases = tuple(b.strip() for b in args.bases.split(",") if b.strip())
    want = [int(v) for v in args.samples.split(",") if v.strip()]
    allrows = []
    for i in want:
        print(f"=== 样 {i}（{'+'.join(bases)}）", flush=True)
        allrows.extend(run(i, bases))
    # 并行跑时不能共用同一个汇总文件（会互相覆盖/撞锁），按进程号命名
    (B.OUT / f"m5_wb_last_{os.getpid()}.json").write_text(
        json.dumps(allrows, ensure_ascii=False, indent=2), encoding="utf-8")
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
