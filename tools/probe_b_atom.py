"""M6 可行性探针：逐**元素** B_iso 到底值不值（不改引擎，纯前向 + solve 复算）。

做法
----
1. 按 `combo_tex_aniso` 同口径跑完整配方，拿到收敛参数与**精修后**的相；
2. 在该收敛点上，把每相的原子 B 按「元素」加一个偏移 δ：
   非氧 δ（阳离子/阴离子骨架）、氧 −δ·(n_nonO/n_O)，**元素间加权和为 0**，
   与已有的逐相 ΔB_iso 正交，不抢它的自由度；
3. 其余参数全部冻结（只留 scale/背景线性层解析求解），扫 δ 看 Rwp 响应。

判据：若整条曲线（δ ∈ [−3, +3]）的变化 < 0.05 pt，说明「逐原子 B」在
这批实样上没有可用信息量，M6 不值得做引擎改造。

用法::

    python tools/probe_b_atom.py --samples 1,7
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
from xinrefinement.core.profile.cif import CifStructure            # noqa: E402
from xinrefinement.core.profile.forward import (                   # noqa: E402
    ProfileParams, aniso_default, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner           # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve     # noqa: E402

DELTAS = (-3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0)


def _window(i: int) -> tuple[float, float]:
    return (10.0, 100.0) if i == 5 else (5.0, 120.0)


def _build(i: int, d: Path, pdir: Path):
    """与 eval_bg_all 同口径（每 6° 一节点）。"""
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


def _reweight_atoms(st: CifStructure, delta: float) -> CifStructure:
    """按元素加 B 偏移（氧吃 −δ·n_nonO/n_O，保证加权和为 0）。"""
    n_o = sum(1 for a in st.atoms if a[0] == "O")
    n_x = len(st.atoms) - n_o
    if n_o == 0 or n_x == 0:
        return st
    shift_o = -delta * n_x / n_o
    new = [(el, x, y, z, occ,
            Bv + (shift_o if el == "O" else delta))
           for (el, x, y, z, occ, Bv) in st.atoms]
    out = CifStructure(st.name, st.cell, new)
    out.spacegroup = st.spacegroup
    out.sg_number = st.sg_number
    out.formula = st.formula
    out.z_declared = st.z_declared
    out.n_asym = st.n_asym
    out.n_sym_ops = st.n_sym_ops
    out.source_path = st.source_path
    # 缓存盐值本身是 tuple（见 forward._phase_peaks），追加一项保证变体不互撞
    salt = getattr(st, "_variant", ())
    out._variant = (salt if isinstance(salt, tuple) else (salt,)) + ("b", delta)
    return out


def _scan(phases, pat, params, fixed, target=None) -> list[dict]:
    """扫 δ；`target=None` 表示所有相一起动，否则只动第 target 相。"""
    rows = []
    for delta in DELTAS:
        ph = [_reweight_atoms(st, delta) if (target is None or k == target)
              else st for k, st in enumerate(phases)]
        t0 = time.time()
        r2 = solve(RefineInputs(pat, ph, params, fixed))
        rows.append({"delta": delta, "rwp": round(float(r2.rwp), 4),
                     "seconds": round(time.time() - t0, 2)})
        print(f"    δ={delta:+.1f} → {r2.rwp:.4f}% "
              f"({rows[-1]['seconds']:.1f}s)", flush=True)
    return rows


def run(i: int, per_phase: bool = False) -> dict:
    d, pdir = next((dd, pp) for k, dd, pp in B.sample_dirs() if k == i)
    cache = B.OUT / f"m6_base_{i}.pkl"
    if cache.exists():
        import pickle
        with cache.open("rb") as fh:
            saved = pickle.load(fh)
        pat, base_rwp = saved["pat"], saved["base_rwp"]
        phases_ref, params = saved["phases"], saved["params"]
        cfg = saved["cfg"]
        print(f"  样{i} 复用收敛点（基线 {base_rwp:.4f}%）", flush=True)
    else:
        import pickle
        pat, phases, prm, cfg = _build(i, d, pdir)
        runner = RecipeRunner()
        res, _recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
        if res is None:
            return {"i": i, "error": "配方无结果"}
        base_rwp = float(res.rwp)
        phases_ref, params = runner.phases, res.params
        with cache.open("wb") as fh:
            pickle.dump({"pat": pat, "base_rwp": base_rwp,
                         "phases": phases_ref, "params": params,
                         "cfg": cfg}, fh)
    fixed = replace(cfg, refine_zero=False, refine_uvw=False, refine_eta=False,
                    refine_asym=False, refine_cell=False, refine_po=False,
                    refine_size=False, refine_strain=False,
                    refine_texture=False, refine_aniso=False,
                    refine_biso=False, refine_xyz=False, po_probe=False)
    rows = []
    for delta in DELTAS:
        ph2 = [_reweight_atoms(st, delta) for st in phases_ref]
        t0 = time.time()
        r2 = solve(RefineInputs(pat, ph2, params, fixed))
        rows.append({"delta": delta, "rwp": round(float(r2.rwp), 4),
                     "seconds": round(time.time() - t0, 2)})
        print(f"  样{i} δ={delta:+.1f} → {r2.rwp:.4f}% "
              f"({rows[-1]['seconds']:.1f}s)", flush=True)
    best = min(rows, key=lambda r: r["rwp"])
    out = {"i": i, "base_rwp": round(base_rwp, 4), "rows": rows,
           "best": best, "gain": round(best["rwp"] - base_rwp, 4)}
    if per_phase:
        # 全局同 δ 的弱点：两相若想要相反的对比方向会互相抵消。
        # 这里逐相单独扫，只在「最大的一相」上跑一次不划算的整相放开。
        pp = []
        for idx, st in enumerate(phases_ref):
            print(f"  样{i} 逐相扫描 [{idx}] {st.name} "
                  f"({len(st.atoms)} 原子)", flush=True)
            prows = _scan(phases_ref, pat, params, fixed, target=idx)
            pb = min(prows, key=lambda r: r["rwp"])
            pp.append({"index": idx, "name": st.name,
                       "n_atoms": len(st.atoms), "rows": prows,
                       "best": pb, "gain": round(pb["rwp"] - base_rwp, 4)})
        out["per_phase"] = pp
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="1,7")
    ap.add_argument("--out", default="m6_probe_b_atom.json")
    ap.add_argument("--per-phase", action="store_true",
                    help="额外逐相单独扫 δ（复用收敛点缓存，成本很低）")
    args = ap.parse_args(argv)
    want = [int(v) for v in args.samples.split(",") if v.strip()]
    out = []
    for i in want:
        print(f"=== 样 {i}", flush=True)
        out.append(run(i, per_phase=args.per_phase))
        print(json.dumps(out[-1], ensure_ascii=False), flush=True)
    (B.OUT / args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 汇总 ===")
    for r in out:
        if "error" in r:
            print(f"样{r['i']}: {r['error']}")
            continue
        b = r["best"]
        print(f"样{r['i']}: 全局同 δ 基线 {r['base_rwp']:.4f} → "
              f"最佳 δ={b['delta']:+.1f} {b['rwp']:.4f}（{r['gain']:+.4f} pt）")
        for p in r.get("per_phase", []):
            pb = p["best"]
            print(f"        逐相 [{p['index']}] {p['name']:<16s} "
                  f"最佳 δ={pb['delta']:+.1f} {pb['rwp']:.4f}"
                  f"（{p['gain']:+.4f} pt）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
