"""样 7：复刻 MAUD 的**逐相混合微结构模型**（M8b 判决实验）。

MAUD 的 ``7#.par`` 不是「所有相一套模型」，而是**按相分开**的：

============  ==========================  ====================================
相            size/strain 模型             参数
============  ==========================  ====================================
Kaolinite     Popa LB（各向异性）          6 参 + Harmonic(6) 织构
CaF₂          Popa LB（各向异性）          6 参 + Harmonic(6) 织构
Quartz        Delft / Isotropic            size 7586 Å、strain 4.0e-7（≈无）
Dolomite      Popa LB（各向异性）          6 参 + Harmonic(8) 织构
Cristobalite  Delft / Isotropic            size 27.17 Å、strain 0.01636（极宽）
============  ==========================  ====================================

我们此前只有两种极端：全相 6 参 Popa LB（``combo_tex_aniso``，基线 14.689）
或全相不展宽。前者让方石英的 6 参张量跑飞——实测某方向 FWHM 1.87°、谱上
只有 0.24°（4.8 倍过宽），于是模型靠 19 维织构在残差里乱填（相邻 bin 在
0.1 与 2.27 之间跳）。

M8b 的 ``size_strain`` 支持**逐相 2 参各向同性**，于是可以一比一复刻 MAUD
的混合模型：三相 Popa LB + 两相各向同性。

变体
----
* ``maud_iso``：按 MAUD 的数值播种（石英 Y=0.0116°，方石英 Y=3.249°、
  X=3.750°；``Y = (180/π)·λ/D``，MAUD 的 Delft 用 K=1）。
* ``free_iso``：同样只给石英/方石英各向同性，但起点取中性 0.05°，让 LM
  自己找——检验「数据本身是否支持一个宽方石英」，而不是「被 MAUD 的起点
  带过去」。

用法::

    python tools/eval_sample7_sizestrain.py                # 两个变体都跑
    python tools/eval_sample7_sizestrain.py --only maud_iso
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

ROOT = Path(r"D:\Project\XRDdata\ShiJK-Refinement")
JSON = "m8_sizestrain.json"
DIRS = sorted(p for p in ROOT.iterdir() if p.is_dir())
RAD2DEG = 57.29577951308232

#: 按相在列表中的 0 基序号：样 7 的 CIF 排序固定（见 bench_v14._load）
ANISO_IDX = (0, 1, 3)        # Kaolinite / CaF2 / Dolomite —— MAUD 的 Popa LB
ISO_IDX = (2, 4)             # Quartz / Cristobalite —— MAUD 的 Delft 各向同性
#: MAUD 的 Delft 数值：(cryst_size Å, microstrain)
MAUD_DELFT = {2: (7586.1597, 4.0229932e-7), 4: (27.168015, 0.016363282)}

#: 全谱背景/窗口口径与 combo_tex_aniso 一致
TMAX = 120.0
NBG = 19


def _y_from_size(d_ang: float, lam: float = 1.5406) -> float:
    """``Y = (180/π)·λ/D``（MAUD Delft 用 K=1，与 Scherrer K=0.9 差 11%）。"""
    return RAD2DEG * lam / float(d_ang)


def _x_from_strain(eps: float) -> float:
    """``X = (180/π)·4ε``。"""
    return RAD2DEG * 4.0 * float(eps)


def _build(variant: str):
    pat, phases = B._load(7, DIRS[6], DIRS[6])
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)

    # 织构：与基线同源（po.json 命中轴 → EWIMV 19 点）
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

    aniso = {phases[i].name: aniso_default(1.5406, 0.0, 0.05)
             for i in ANISO_IDX}
    ss: dict[str, tuple[float, float]] = {}
    for i in ISO_IDX:
        if variant == "maud_iso" and i in MAUD_DELFT:
            d_ang, eps = MAUD_DELFT[i]
            ss[phases[i].name] = (_x_from_strain(eps), _y_from_size(d_ang))
        else:
            ss[phases[i].name] = (0.0, 0.05)
    prm = replace(prm, aniso=aniso, size_strain=ss)

    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=NBG,
                       bg_mode="tent", tmin=5.0, tmax=TMAX, max_iter=40,
                       po_probe=False, refine_biso=True, refine_xyz=True,
                       refine_texture=bool(best), refine_aniso=True,
                       refine_eta=True, refine_size_strain=True)
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
    for r in rows:
        if r.get("rwp_pct") is None:
            print(f"{r['variant']}: failed")
            continue
        cr = next((q["vol_pct"] for q in r.get("qpa", [])
                   if "8234" in q["name"]), None)
        print(f"{r['variant']:<10} Rwp={r['rwp_pct']:.3f}  "
              f"gap={r['rwp_pct'] - 11.30:+.2f}  方石英={cr}  "
              f"{r['seconds']:.0f}s")
        if r.get("size_strain"):
            for k, v in r["size_strain"].items():
                print(f"    {k.split()[-1]:<8} X={v[0]:.4f} Y={v[1]:.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="maud_iso / free_iso")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if args.report:
        return _report()

    rows = B._read_json(JSON)
    done = {r["variant"] for r in rows}
    want = [args.only] if args.only else ["maud_iso", "free_iso"]
    for variant in want:
        if variant in done:
            print(f"{variant} 已有结果，跳过", flush=True)
            continue
        pat, phases, prm, cfg = _build(variant)
        t0 = time.time()
        try:
            res, recs = RecipeRunner().run_all(
                RefineInputs(pat, phases, prm, cfg))
        except Exception as exc:                                  # noqa: BLE001
            print(f"{variant} 异常 {type(exc).__name__}: {exc}", flush=True)
            continue
        if res is None:
            print(f"{variant} 配方无结果", flush=True)
            continue
        row = {"variant": variant, "rwp_pct": float(res.rwp),
               "seconds": round(time.time() - t0, 1),
               "qpa": _qpa(res),
               "size_strain": {k: [round(float(v[0]), 5), round(float(v[1]), 5)]
                               for k, v in (res.params.size_strain or {}).items()},
               "biso": {k: round(float(v), 3)
                        for k, v in (res.params.b_iso or {}).items()},
               "steps": [(r.key, r.status,
                          None if r.rwp_after is None else round(r.rwp_after, 3),
                          r.message[:90]) for r in recs]}
        rows = [r for r in rows if r["variant"] != variant] + [row]
        B._write_json(JSON, rows)
        print(json.dumps({"variant": variant, "rwp_pct": row["rwp_pct"],
                          "seconds": row["seconds"]}, ensure_ascii=False),
              flush=True)
        for s in row["steps"]:
            print("   ", s[0], s[1], s[2], s[3], flush=True)
    print()
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
