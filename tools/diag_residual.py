"""v1.5 诊断：逐样残差定位（哪段 2θ / 哪些相在贡献 Rwp）。

不做任何建模，只回答一个问题：**差距集中在哪**。输出

- 每个 2θ 区间的「分区间 Rwp 贡献」(sqrt(Σw r²)/sqrt(Σw y²)·100)；
- 区间内 yobs / ycalc / 残差均值（正值 = 计算谱偏高）；
- 该区间内各相最强反射（便于归属）。

用法::

    python tools/diag_residual.py 7 [--tex] [--aniso] [--bin 5]
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xinrefinement.core.patterns import load_pattern          # noqa: E402
from xinrefinement.core.profile.cif import parse_cif          # noqa: E402
from xinrefinement.core.profile.forward import (              # noqa: E402
    aniso_default, compute_phase_profile, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig   # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve  # noqa: E402

#: 数据集根可用环境变量覆盖（2026-11-12 数据集迁到 d:\test_XRD，旧盘符已不存在）。
ROOT = Path(os.environ.get("XR_BENCH_ROOT", r"d:\test_XRD\ShiJK-Refinement"))
S5PHASE = Path(os.environ.get("XR_BENCH_S5PHASE",
                              r"C:\Temp\maud_compare\s5phase"))
OUT = Path(os.environ.get("XR_BENCH_OUT", r"C:\Temp\maud_compare\v14"))


def _sample(i: int):
    dirs = sorted(p for p in ROOT.iterdir() if p.is_dir())
    d = dirs[i - 1]
    # 与 bench_v14.sample_dirs 同规则：s5phase 只在存在时覆盖样本目录
    pdir = S5PHASE if (i == 5 and S5PHASE.is_dir()) else d
    pat = load_pattern(next(d.glob("*.txt")))
    phases = [parse_cif(c) for c in sorted(pdir.glob("*.cif"))]
    return d, pat, phases


def _best_axis(i: int) -> dict:
    po = OUT / "po.json"
    if not po.exists():
        return {}
    import json

    rows = json.loads(po.read_text(encoding="utf-8"))
    best: dict = {}
    for r in rows:
        if (r.get("i") == i and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v) for v in r["axis"])
            if ph not in best or r["delta"] < best[ph][1]:
                best[ph] = (ax, r["delta"])
    return {ph: ax for ph, (ax, _d) in best.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", type=int)
    ap.add_argument("--tex", action="store_true", help="叠加 EWIMV 织构")
    ap.add_argument("--aniso", action="store_true", help="叠加 Popa LB")
    ap.add_argument("--bin", type=float, default=5.0, dest="binsz")
    a = ap.parse_args(argv)

    i = a.sample
    d, pat, phases = _sample(i)
    with (OUT / f"base_{i}.pkl").open("rb") as fh:
        b = pickle.load(fh)
    ph_path = OUT / f"base_{i}_phases.pkl"
    if ph_path.exists():
        with ph_path.open("rb") as fh:
            phases = pickle.load(fh)
    prm, cfg0 = b["prm"], b["cfg"]
    tmin, tmax = (10.0, 100.0) if i == 5 else (5.0, 120.0)
    nbg = max(6, int(round((tmax - tmin) / 6.0)))
    cfg = replace(cfg0, tmin=tmin, tmax=tmax, n_bg=nbg, bg_mode="tent",
                  refine_zero=False, refine_uvw=False, refine_eta=False,
                  refine_asym=False, refine_bfactor=False, refine_cell=False,
                  refine_po=False, refine_size=False, refine_strain=False,
                  refine_texture=False, refine_aniso=False,
                  refine_biso=False, refine_microabs=False, po_probe=False,
                  max_iter=25)
    base = solve(RefineInputs(pat, phases, prm, cfg))
    print(f"[{d.name}] 增量基线 Rwp = {base.rwp:.3f}%")

    cur, cur_prm = base, prm
    if a.tex:
        ax = _best_axis(i)
        if ax:
            tex = {n: {"axis": v, "grid": default_texture_grid()}
                   for n, v in ax.items()}
            c2 = replace(cfg, refine_texture=True, max_iter=25)
            cur = solve(RefineInputs(pat, phases, replace(cur_prm, texture=tex),
                                     c2))
            cur_prm = cur.params
            print(f"  + EWIMV 织构（{len(ax)} 相） → {cur.rwp:.3f}%")
        else:
            print("  （po.json 无命中轴，跳过织构）")
    if a.aniso:
        an = {st.name: aniso_default(prm.wavelength, prm.X, prm.Y or 0.05)
              for st in phases}
        c3 = replace(cfg, refine_aniso=True, aniso_auto=True, max_iter=25)
        cur = solve(RefineInputs(pat, phases, replace(cur_prm, aniso=an),
                                 c3))
        cur_prm = cur.params
        print(f"  + Popa LB（auto） → {cur.rwp:.3f}%")

    # 缓存精修结果，供后续细查（1° bin / 最差点位）免重算
    tag = "".join(x for x in ("t" if a.tex else "", "a" if a.aniso else "")
                  if x) or "base"
    with (OUT / f"diag_{i}_{tag}.pkl").open("wb") as fh:
        pickle.dump({"params": cur.params, "cfg": cur.config,
                     "pattern": cur.pattern, "ycalc": cur.ycalc,
                     "rwp": float(cur.rwp), "phases": phases}, fh)

    tt = cur.pattern.two_theta
    yo = cur.pattern.intensity
    yc = cur.ycalc
    w = 1.0 / np.maximum(yo, 1.0)
    r = yo - yc
    print(f"\n分区间残差（bin={a.binsz:g}°，总 Rwp={cur.rwp:.3f}%）")
    print(f"{'区间':>12s} {'贡献%':>7s} {'占总量%':>8s} {'<残差>':>9s} "
          f"{'yobs均值':>9s}")
    edges = np.arange(tmin, tmax + 1e-9, a.binsz)
    tot = float(np.sum(w * r * r))
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (tt >= lo) & (tt < hi)
        if not bool(m.any()):
            continue
        ss = float(np.sum(w[m] * r[m] ** 2))
        rr = 100.0 * np.sqrt(ss / max(float(np.sum(w[m] * yo[m] ** 2)), 1e-12))
        rows.append((lo, hi, rr, 100.0 * ss / max(tot, 1e-12),
                     float(np.mean(r[m])), float(np.mean(yo[m]))))
    rows.sort(key=lambda x: -x[3])
    for lo, hi, rr, frac, mr, my in rows:
        print(f"{lo:5.0f}–{hi:<6.0f} {rr:7.2f} {frac:8.1f} {mr:9.1f} {my:9.1f}")

    print("\n各相最强反射位置（用于归属上面高贡献区间）")
    for st in phases:
        y = compute_phase_profile(st, tt, cur_prm, tmin, tmax)
        if y.size == 0 or not np.any(y > 0):
            continue
        idx = np.argsort(y)[-3:][::-1]
        tops = ", ".join(f"{tt[k]:.1f}°" for k in idx)
        print(f"  {st.name[:32]:32s} {tops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
