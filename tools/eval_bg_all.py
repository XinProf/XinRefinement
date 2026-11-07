"""背景节点密度：7 样全量评测（M8c 决策数据）。

背景
----
样 7 上 tent 背景节点从 19（每 6° 一节点）加密到 45（每 2.5°）Rwp 单调降到
14.142（−0.55），方石英 vol% 稳定在 6.75–7.64。方向上这更接近 MAUD——它用
「插值背景 + 10 轮迭代」，比 19 节点 tent 灵活得多。但把默认值改成每 2.5°
一节点是**全样生效**的改动，必须先看样 1–6 的 Rwp 与 QPA 才能定。

本脚本对每样跑**两档**：默认档（每 6°，应逐位复现 `combo_tex_aniso`
基准）与加密档（每 2.5°）。两档同一进程同一起点，差异只能归因到背景。

口径
----
与 `bench_v14 combo_tex_aniso` 完全一致：PO 探索关、逐相 ΔB_iso、xyz、
EWIMV 织构（po.json 命中轴）、Popa LB、η；窗口 5–120°，**样 5 为 10–100°**
（其数据只到 100°）。

用法
----
    python tools/eval_bg_all.py --samples 1,2,3
    python tools/eval_bg_all.py --report
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

JSON = "m8_bg_all.json"


def _row_file(i: int) -> str:
    """每样一个文件。

    踩过的坑：7 个 worker 并行跑时共用一个 JSON，写法是「读—改—写」，
    于是后写的进程会把先写的行覆盖掉（实测样 3 的 2.5° 结果被样 6 覆盖
    丢失）。按样分文件后，同一样只有串行写入，彻底消除竞争。
    """
    return f"m8_bg_{i}.json"


def _all_rows() -> dict[tuple[int, float], dict]:
    """合并所有分片（含历史的单文件），键为 (样号, spacing)。"""
    out: dict[tuple[int, float], dict] = {}
    # 历史单文件（旧版共用文件，可能被并行写覆盖）先读，分片后读覆盖它，
    # 保证以「每样一个文件」的结果为准。
    files = sorted(B.OUT.glob("m8_bg_*.json"),
                   key=lambda p: (p.name != JSON, p.name))
    for p in files:
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            if "i" not in r or "spacing" not in r:
                continue
            out[(int(r["i"]), float(r["spacing"]))] = r
    return out
#: MAUD 实测（§1.7 表）
MAUD = {1: 10.90, 2: 6.34, 3: 10.29, 4: 9.96, 5: 14.87, 6: 14.76, 7: 11.30}


def _window(i: int) -> tuple[float, float]:
    return (10.0, 100.0) if i == 5 else (5.0, 120.0)


def _build(i: int, d: Path, pdir: Path, spacing: float):
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
    nbg = max(6, int(round((tmax - tmin) / spacing)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40,
                       po_probe=False, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True)
    return pat, phases, prm, cfg, nbg


def _qpa(res) -> list[dict]:
    raw = [p.scale * p.volume ** 2 for p in res.phases]
    tot = sum(raw) or 1.0
    return [{"name": p.name, "vol_pct": round(100 * r / tot, 2)}
            for p, r in zip(res.phases, raw)]


def _report() -> int:
    """打印全样表。

    列按**实际存在的 spacing** 生成（历史 6.0/2.5 + 后补的 4.0 中间档），
    稀疏/加密的相对量都以 6.0° 为参照——它是出厂自适应档，也是
    `combo_tex_aniso` 基准的复现点。
    """
    rows = list(_all_rows().values())
    if not rows:
        print("尚无结果")
        return 0
    by: dict[int, dict[float, dict]] = {}
    for r in rows:
        by.setdefault(r["i"], {})[float(r["spacing"])] = r
    spaces = sorted({sp for d in by.values() for sp in d})
    # 6.0° 打头（出厂自适应档 = 基准复现点），其余按由疏到密排列
    spaces = ([6.0] if 6.0 in spaces else []) + [s for s in spaces if s != 6.0]
    head = f"{'样':>2} {'MAUD':>6}"
    for sp in spaces:
        head += f" {f'{sp:g}°':>7} {'Δ':>7}"
    head += f" {'gap@密':>7}  {'max|Δvol%|':>16}"
    print(head)
    for i in sorted(by):
        d = by[i]
        base = d.get(6.0)
        if base is None or base.get("rwp_pct") is None:
            print(f"{i:>2} 缺 6.0° 基准档")
            continue
        line = f"{i:>2} {MAUD.get(i, 0):6.2f}"
        for sp in spaces:
            r = d.get(sp)
            if r is None or r.get("rwp_pct") is None:
                line += f" {'—':>7} {'':>7}"
                continue
            line += f" {r['rwp_pct']:7.3f} {r['rwp_pct'] - base['rwp_pct']:+7.3f}"
        # 相对 MAUD 的差距只在最密档给一列：逐列给会把表撑到读不下去
        densest = [d[sp] for sp in spaces if d.get(sp)
                   and d[sp].get("rwp_pct") is not None][-1]
        gap = (f"{densest['rwp_pct'] - MAUD[i]:+.2f}"
               if i in MAUD else "—")
        # QPA 漂移用「全相最大 |Δvol%|」而不是盯某一相：背景加密最怕的是
        # 把重叠峰强度吸进本底，任何相的分数都可能动，只看方石英会漏。
        qa = {q["name"]: q["vol_pct"] for q in base.get("qpa", [])}
        worst, who, worst_sp = 0.0, "—", None
        for sp in spaces:
            r = d.get(sp)
            if r is None or sp == 6.0:
                continue
            qb = {q["name"]: q["vol_pct"] for q in r.get("qpa", [])}
            for name in set(qa) & set(qb):
                delta = abs(qb[name] - qa[name])
                if delta > worst:
                    worst, who, worst_sp = delta, name.split()[-1], sp
        tag = f"{worst:5.2f} @{worst_sp:g}° ({who})" if worst_sp else "—"
        print(line + f" {gap:>7}  {tag:>16}")
    if by:
        print("\n（Δ 为相对 6.0° 出厂档的 Rwp 变化，负数 = 改善；"
              "max|Δvol%| 为任一相 QPA 相对 6.0° 的最大漂移）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="1,2,3,4,5,6,7")
    ap.add_argument("--spacing", default="6.0,2.5")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        return _report()

    want = {int(v) for v in args.samples.split(",") if v.strip()}
    spaces = [float(v) for v in args.spacing.split(",") if v.strip()]
    done = set(_all_rows())
    for i, d, pdir in B.sample_dirs():
        if i not in want:
            continue
        for sp in spaces:
            if (i, sp) in done:
                continue
            pat, phases, prm, cfg, nbg = _build(i, d, pdir, sp)
            t0 = time.time()
            try:
                res, recs = RecipeRunner().run_all(
                    RefineInputs(pat, phases, prm, cfg))
            except Exception as exc:                              # noqa: BLE001
                print(f"样{i} spacing={sp} 异常 {type(exc).__name__}: {exc}",
                      flush=True)
                continue
            if res is None:
                print(f"样{i} spacing={sp} 配方无结果", flush=True)
                continue
            row = {"i": i, "spacing": sp, "n_bg": nbg,
                   "rwp_pct": float(res.rwp),
                   "seconds": round(time.time() - t0, 1),
                   "qpa": _qpa(res),
                   "biso": {k: round(float(v), 3)
                            for k, v in (res.params.b_iso or {}).items()},
                   "steps": [(r.key, r.status,
                              None if r.rwp_after is None else round(r.rwp_after, 3))
                             for r in recs]}
            name = _row_file(i)
            rows = [r for r in (B._read_json(name) or [])
                    if float(r["spacing"]) != sp] + [row]
            B._write_json(name, rows)
            print(json.dumps({"i": i, "spacing": sp, "n_bg": nbg,
                              "rwp_pct": round(row["rwp_pct"], 3),
                              "seconds": row["seconds"]}, ensure_ascii=False),
                  flush=True)
    print()
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
