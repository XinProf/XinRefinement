"""v1.5 M8：样 7 方石英多型替换后的**完整配方**验证。

诊断（`tools/diag_residual.py`）表明样 7 的差距不是峰宽、不是背景，而是
方石英结构：21.86° 主峰顶点计算值只有观测的 53%，且该相 `ΔB_iso` 撞
6 Å² 上界——典型的「多型/结构模型错」信号。

`eval_cristobalite.py models_m4m5` 的增量对照已给出结论（β 18.06 →
α 15.59）。本脚本把**同一替换**放进完整配方链（cell/profile/xyz/micro/B），
给出可与 MAUD 直接比较的端到端数字。

用法::

    python tools/eval_sample7_alpha.py            # α (96-900-9688)
    python tools/eval_sample7_alpha.py s6         # α (96-901-7339)
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
from xinrefinement.core.profile.cif import parse_cif                # noqa: E402
from xinrefinement.core.profile.forward import (                    # noqa: E402
    ProfileParams, aniso_default, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig        # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner           # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs            # noqa: E402

ROOT = Path(r"D:\Project\XRDdata\ShiJK-Refinement")
OUT = B.OUT
DIRS = sorted(p for p in ROOT.iterdir() if p.is_dir())
D7 = DIRS[6]
ALPHA = {"s4": DIRS[3] / "1-cristobalite-Entry_96-900-9688.cif",
         "s6": DIRS[5] / "4-cristobalite-Entry_96-901-7339.cif",
         # 对照：不换相（仍是用户给的 β Fd-3m），用来把「换多型」的收益
         # 与「本脚本与 combo_tex_aniso 的口径差（PO 试探同时开着）」分开
         "beta": None}


def main(argv: list[str]) -> int:
    which = "s4"
    nbg_override = 0
    rest = [a for a in argv[1:]]
    if rest and not rest[0].startswith("--"):
        which = rest.pop(0)
    if "--nbg" in rest:
        nbg_override = int(rest[rest.index("--nbg") + 1])
    pat, phases = B._load(7, D7, D7)
    from eval_cristobalite import _crist_index

    idx = _crist_index(phases)
    crist_name = phases[idx].name
    if ALPHA[which] is None:            # beta 对照：原样使用用户 CIF
        pass
    else:
        alpha = parse_cif(ALPHA[which])
        alpha.name = crist_name
        phases = list(phases)
        phases[idx] = alpha

    # 与 combo_tex_aniso 完全同口径的输入构造（见 bench_v14._full_recipe）
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    po = B._read_json("po.json")
    best: dict = {}
    for r in po:
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

    tmin, tmax = 5.0, 120.0
    nbg = nbg_override or max(6, int(round((tmax - tmin) / 6.0)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40,
                       po_probe=True, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True)
    t0 = time.time()
    runner = RecipeRunner()
    res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
    if res is None:
        print("配方无结果")
        return 1
    row = {"stage": "s7_alpha", "which": which, "n_bg": nbg,
           "cif": None if ALPHA[which] is None else str(ALPHA[which]),
           "rwp_pct": float(res.rwp),
           "seconds": round(time.time() - t0, 1),
           "weights": [(p.name, None if p.weight_pct is None
                        else round(float(p.weight_pct), 2))
                       for p in res.phases],
           "biso": {k: round(float(v), 4)
                    for k, v in (res.params.b_iso or {}).items()},
           "biso_hit": sorted(k for k, v in (res.params.b_iso or {}).items()
                              if float(v) >= 5.99),
           "steps": [(r.key, r.status, None if r.rwp_after is None
                      else round(r.rwp_after, 3), r.message[:90])
                     for r in recs]}
    rows = B._read_json("s7_alpha.json")
    rows = [r for r in rows if (r.get("which"), r.get("n_bg", 0))
            != (which, nbg)] + [row]
    B._write_json("s7_alpha.json", rows)
    print(json.dumps({k: row[k] for k in
                      ("which", "rwp_pct", "biso_hit", "seconds")},
                     ensure_ascii=False))
    for s in row["steps"]:
        print("  ", s[0], s[1], s[2], s[3])
    print(f"MAUD 同数据 = 11.30%   差距 = {row['rwp_pct'] - 11.30:+.2f} pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
