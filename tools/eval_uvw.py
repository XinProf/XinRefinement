"""v1.5 诊断：样 7 峰宽模型对照（我们的 Caglioti vs MAUD 实测 U/V/W）。

问题：样 7 的 Caglioti 精修到 U=0.418 / V=-0.239 / W=0.049（90°处 FWHM
0.478°），而 MAUD 在同一数据上精修出 U=0.00253 / V=0.00272 / W=0.00231
（90°处 0.087°）。峰宽差 5 倍意味着高角峰被过度铺宽 -> 谷底系统性偏高。

本脚本在**同一模型其余部分完全不变**的前提下，只换 U/V/W：
- ``ours``：当前精修值；
- ``maud``：MAUD 的 U/V/W（不精修峰宽）；
- ``maud_refit``：从 MAUD 值起再放开精修（看是否会跑回去）。
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                              # noqa: E402
from xinrefinement.core.profile.forward import (                   # noqa: E402
    default_texture_grid)
from xinrefinement.core.refine.solve import RefineInputs, solve     # noqa: E402

ROOT = Path(r"D:\Project\XRDdata\ShiJK-Refinement")
OUT = B.OUT
#: MAUD 2.99993 在样 7 上精修出的 Caglioti 参数（7#.par L314 起）
MAUD_UVW = (0.00252935, 0.002716717, 0.002312246)


def main(argv: list[str]) -> int:
    i = int(argv[1]) if len(argv) > 1 else 7
    dirs = sorted(p for p in ROOT.iterdir() if p.is_dir())
    d = dirs[i - 1]
    pdir = B.S5PHASE if i == 5 else d
    pat = B._load(i, d, pdir)[0]
    b = B._load_base(i)
    phases = B._refined_phases(i, d, pdir)

    po = B._read_json("po.json")
    best: dict = {}
    for r in po:
        if (r.get("i") == i and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v) for v in r["axis"])
            if ph not in best or r["delta"] < best[ph][1]:
                best[ph] = (ax, r["delta"])
    tex = {ph: {"axis": ax, "grid": default_texture_grid()}
           for ph, (ax, _d) in best.items()}

    tmin, tmax = (10.0, 100.0) if i == 5 else (5.0, 120.0)
    nbg = max(6, int(round((tmax - tmin) / 6.0)))
    base_cfg = replace(b["cfg"], tmin=tmin, tmax=tmax, n_bg=nbg,
                       bg_mode="tent", refine_texture=bool(tex),
                       refine_aniso=True, aniso_auto=True, refine_biso=False,
                       refine_po=False, refine_zero=False, refine_eta=False,
                       refine_asym=False, max_iter=25)

    # 注意：refine_uvw=True 会在「Rwp > 10%」时触发 3 点重启链（成本 ×4，
    # 真实样必然 >10%），本对照要的是**同模型只换峰宽**，故一律不放开 UVW，
    # 用两个固定点比较；顺带避开重启链的时间开销。
    ours_uvw = (float(b["prm"].U), float(b["prm"].V), float(b["prm"].W))
    rows = []
    for label, uvw, refit in (
        ("ours_fixed", ours_uvw, False),
        ("maud_fixed", MAUD_UVW, False),
    ):
        prm = replace(b["prm"], texture=(tex or None), aniso=None)
        if uvw is not None:
            prm = replace(prm, U=uvw[0], V=uvw[1], W=uvw[2])
        cfg = replace(base_cfg, refine_uvw=refit)
        t0 = time.time()
        res = solve(RefineInputs(pat, phases, prm, cfg))
        p = res.params
        row = {"stage": "uvw", "sample": i, "case": label,
               "rwp_pct": float(res.rwp),
               "uvw": [round(p.U, 6), round(p.V, 6), round(p.W, 6)],
               "eta": round(p.eta, 4),
               "sec": round(time.time() - t0, 1)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    B._write_json(f"uvw_{i}.json", rows)
    ours = rows[0]["rwp_pct"]
    print(f"\n参考：样 {i} 当前口径 Rwp={ours:.3f}%")
    for r in rows[1:]:
        print(f"  {r['case']:12s} Rwp={r['rwp_pct']:.3f}%  "
              f"Δ={r['rwp_pct'] - ours:+.3f} pt  UVW={r['uvw']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
