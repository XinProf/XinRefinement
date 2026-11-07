"""M3 实测：同一配方链下，EWIMV 19 点网格 vs 球谐 Legendre 展开。

口径与 ``bench_v14.py stage_combo_tex_aniso`` **严格一致**（同 tmin/tmax、
同 n_bg、同 ``extra`` 开关、同 po.json 选轴），**只换织构模型**，因此
Rwp 差可直接归因到织构模型本身。

为什么值得换
------------
``combo_tex_aniso`` 落盘的 7 样 EWIMV 网格呈现典型的「不可辨识 + 过拟合」
形态：相邻 χ bin 在 0.1（下界）与 6.9 之间乱跳，例如样 1 的方解石

    [1.03, 1.25, 1.52, 1.16, 0.1, 0.1, 0.38, 0.1, 0.1, 0.44, ...]

物理上真实的 ODF 是光滑的。19 维自由参数在单谱上远超可辨识信息量，
只能靠二阶差分罚勉强兜住；球谐用 2–4 个正交基系数表达同一件事，
条件数好、无尺度零空间，且与 MAUD ``Harmonic``（阶 6/8）同类。

用法
----
    python tools/eval_texture_m3.py --model harmonic:4 --samples 1,5,7
    python tools/eval_texture_m3.py --model ewimv --samples 1      # 复现对照
    python tools/eval_texture_m3.py --report                       # 汇总已跑结果

结果落 ``C:/Temp/maud_compare/v14/m3_<tag>.json``（逐样追加，可断点续跑）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                        # noqa: E402
from xinrefinement.core.profile.forward import (              # noqa: E402
    ProfileParams,
    aniso_default,
    default_texture_coeffs,
    default_texture_grid,
)
from xinrefinement.core.refine.nonlinear import RefineConfig   # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner      # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs       # noqa: E402

#: 与 combo_tex_aniso 完全相同的开关组合（M4/M5 口径）
EXTRA = {"po_probe": False, "refine_biso": True, "refine_xyz": True,
         "refine_texture": True, "refine_aniso": True, "refine_eta": True}


def _tag(model: str) -> str:
    return str(model).replace(":", "")


def _texture_entry(axis, model: str) -> dict:
    mdl, _, deg = str(model).partition(":")
    if mdl == "harmonic":
        d = int(deg or 4)
        return {"axis": axis, "model": "harmonic", "degree": d,
                "coeffs": default_texture_coeffs(d)}
    return {"axis": axis, "grid": default_texture_grid()}


def _seed_texture(i: int, model: str) -> dict:
    """按 po.json 的增益轴给该样挑织构相（与 bench 的自动初始化同源）。"""
    best: dict = {}
    for r in B._read_json("po.json"):
        if (r.get("i") == i and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph = r["phase"]
            ax = tuple(int(v) for v in r["axis"])
            if ph not in best or r["delta"] < best[ph][1]:
                best[ph] = (ax, r["delta"])
    return {ph: _texture_entry(ax, model) for ph, (ax, _d) in best.items()}


def run_one(i: int, d: Path, pdir: Path, model: str, tmax: float = 120.0,
            aniso_skip: set[int] | None = None, aniso_mode: str = "",
            tex_extra: str = ""):
    """跑一样：配方链不变，只把织构模型换成 ``model``。

    ``tex_extra``：形如 ``"1:1,0,1;3:0,0,1"``，按 1 基相序号额外开织构
    并指定纤维轴。用来验证 §2.1 的核心发现——MAUD 是**逐相**选模型的，
    而基准脚本只从 ``po.json`` 取达到试探阈值的相（会漏相）。

    ``tmax`` 默认 **120°**——必须与 ``bench_v14.stage_combo_tex_aniso``
    调 ``_full_recipe(i, d, pdir, extra, 120.0)`` 的口径一致。曾误用 90°
    导致两组数字不可比（样 7 的萤石在 5–90° 内独立晶向只有 7 个，
    直接撞各向异性护栏 `ANISO_MIN_DIRS=8`，micro 步整体失败）。

    ``aniso_skip``：按相在列表中的**1 基序号**排除各向异性（对齐 MAUD
    「只对部分相用 Popa LB、其余用 Delft 2 参」的逐相选择）。
    ``aniso_mode``：留空＝沿用 ``RefineConfig`` 默认 ``"size"``（6 参/相，
    与 ``combo_tex_aniso`` 基准口径一致）；``both`` 才是 12 参。
    """
    pat, phases = B._load(i, d, pdir)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    tex = _seed_texture(i, model)
    for item in str(tex_extra or "").split(";"):
        if not item.strip():
            continue
        idx_s, _, hkl_s = item.partition(":")
        j = int(idx_s.strip())
        hkl = tuple(int(v) for v in hkl_s.split(","))
        if not 1 <= j <= len(phases) or len(hkl) != 3 or hkl == (0, 0, 0):
            raise ValueError(f"--tex-extra 非法项: {item!r}")
        tex[phases[j - 1].name] = _texture_entry(hkl, model)
    if tex:
        prm = replace(prm, texture=tex)
    skip = set(aniso_skip or ())
    aniso = {st.name: aniso_default(1.5406, 0.0, 0.05)
             for j, st in enumerate(phases, 1) if j not in skip}
    if aniso:
        prm = replace(prm, aniso=aniso)
    tmin = 5.0
    if i == 5:            # 样 5b 数据仅 10–100°，与 MAUD 同口径
        tmin, tmax = 10.0, 100.0
    nbg = max(6, int(round((tmax - tmin) / 6.0)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40)
    extra = dict(EXTRA)
    if aniso_mode:
        extra["aniso_mode"] = aniso_mode
    cfg = replace(cfg, **extra)
    runner = RecipeRunner()
    t0 = time.time()
    res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
    return res, recs, runner, round(time.time() - t0, 1), tex


def _dump_tex(tex: dict | None) -> dict:
    out = {}
    for name, e in (tex or {}).items():
        if (e or {}).get("model") == "harmonic":
            out[name] = {"degree": e.get("degree"),
                         "coeffs": [round(float(v), 4)
                                    for v in (e.get("coeffs") or [])]}
        else:
            out[name] = {"grid": [round(float(v), 3)
                                 for v in (e.get("grid") or [])]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="harmonic:4",
                    help="ewimv | harmonic:4 | harmonic:6 | harmonic:8")
    ap.add_argument("--samples", default="1,5,7")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--out", default="",
                    help="自定义结果文件名（并行跑不同样品时避免互相覆盖）")
    ap.add_argument("--aniso-skip", default="",
                    help="按 1 基相序号排除各向异性，如 4,5（对齐 MAUD 逐相选择）")
    ap.add_argument("--aniso-mode", default="",
                    help="留空=size（与基准口径一致）；size | strain | both")
    ap.add_argument("--tex-extra", default="",
                    help='额外按相序号开织构，如 "1:1,0,1;3:0,0,1"（1 基序号:纤维轴）')
    args = ap.parse_args()

    if args.report:
        report()
        return

    want = {int(v) for v in str(args.samples).split(",") if v.strip()}
    tag = _tag(args.model)
    name = args.out or f"m3_{tag}.json"
    rows = B._read_json(name)
    done = {r["i"] for r in rows}
    for i, d, pdir in B.sample_dirs():
        if want and i not in want:
            continue
        if i in done:
            print(f"[skip] 样 {i} 已完成", flush=True)
            continue
        try:
            res, recs, runner, secs, seed = run_one(
                i, d, pdir, args.model,
                aniso_skip={int(v) for v in
                            str(args.aniso_skip).split(",") if v.strip()},
                aniso_mode=args.aniso_mode, tex_extra=args.tex_extra)
            row = {"i": i, "sample": d.name, "model": args.model,
                   "aniso_skip": sorted(args.aniso_skip and
                                        {int(v) for v in
                                         str(args.aniso_skip).split(",")
                                         if v.strip()} or []),
                   "aniso_mode": args.aniso_mode or "size",
                   "rwp_pct": float(res.rwp), "seconds": secs,
                   "texture": _dump_tex(res.params.texture),
                   "seed_axis": {k: list(v["axis"]) for k, v in seed.items()},
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "steps": [(r.key, r.status,
                              None if r.rwp_after is None else
                              round(float(r.rwp_after), 3), r.message[:110])
                             for r in recs]}
        except Exception as exc:                                   # noqa: BLE001
            row = {"i": i, "sample": d.name, "model": args.model,
                   "rwp_pct": None, "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        B._write_json(name, rows)
        print(json.dumps({"model": args.model, "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "seconds": row.get("seconds")},
                         ensure_ascii=False), flush=True)
    report()


#: MAUD 2 实测（读自各 *.par.lst 的 ``Global Rwp``，样 6 取 6b#.par）
MAUD = {1: 10.90, 2: 6.34, 3: 10.29, 4: 9.96, 5: 14.87, 6: 14.76, 7: 11.30}
#: v1.4/v1.5 已落盘的最佳口径（combo_tex_aniso = EWIMV + Popa LB）
EWIMV = {1: 12.596, 2: 7.724, 3: 10.385, 4: 10.186, 5: 17.204, 6: 12.603,
         7: 17.193}


def report() -> None:
    """把已跑的各 tag 汇总成表（缺失留 —；同一样品多份结果取最优）。"""
    tags: dict[str, dict[int, float]] = {}
    for p in sorted(B.OUT.glob("m3_*.json")):
        tag = p.stem[3:]
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        for r in rows:
            v = r.get("rwp_pct")
            if v is None:
                continue
            cur = tags.setdefault(tag, {}).get(r["i"])
            if cur is None or float(v) < cur:   # 并行跑可能重复，取更好的一条
                tags[tag][r["i"]] = float(v)

    print("\n| 样品 | MAUD | EWIMV+Popa | "
          + " | ".join(tags) + " |")
    print("|---|---|---|" + "---|" * len(tags))
    for i in sorted(MAUD):
        cells = []
        for tag in tags:
            v = tags[tag].get(i)
            cells.append("—" if v is None else f"{v:.3f}")
        print(f"| {i} | {MAUD[i]:.2f} | {EWIMV[i]:.3f} | "
              + " | ".join(cells) + " |")
    for tag in tags:
        vals = [v for v in tags[tag].values() if v is not None]
        if len(vals) == 7:
            print(f"\n{tag}: 均值 {sum(vals) / 7:.3f}% "
                  f"（MAUD 11.20，EWIMV 12.56）")


if __name__ == "__main__":
    main()
