"""v1.5 M8：样 7 方石英「MAUD 同款宽包起点」的完整配方验证。

背景
----
样 7 目录的方石英 CIF（Entry_96-900-8234）本就是 **β 相（Fd-3m，273 °C
高温结构）**，与 MAUD ``7#.par`` 用的是同一相；差别只在展宽模型——

- MAUD：Delft 各向同性，cryst_size = 27.168 Å + rs_microstrain = 0.0164
  （近非晶宽包），定量 vol% = 32.0；
- 我方：``_full_recipe`` 给每相的 aniso 起点都是窄峰
  ``aniso_default(λ, 0, 0.05)``，定量 vol% = 6.84，萤石被顶到 32%。

21.9° 主峰 20–30° 分箱占全谱加权 SS 的 48.1%，局部 Rwp 18.4——
缺口主体是不是「窄峰起点 → 局部极小」，用本脚本直接回答：把方石英相的
aniso 起点换成 MAUD 同款宽包（其余相不变、其余口径与
``eval_shijk_report`` 逐位一致），跑完整配方链对比。

用法::

    python tools/eval_sample7_m8.py               # 全部未完成变体（每个 ~20 min）
    python tools/eval_sample7_m8.py wide_maud     # 只跑一个变体

输出 ``C:/Temp/maud_compare/v14/s7_m8.json``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                             # noqa: E402
from eval_cristobalite import _crist_index                        # noqa: E402
from xinrefinement.core.profile.cif import parse_cif              # noqa: E402
from xinrefinement.core.profile.forward import (                  # noqa: E402
    _RAD2DEG, SCHERRER_K, ProfileParams, aniso_default,
    default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig      # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner         # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs          # noqa: E402

OUT = B.OUT
D7 = sorted(p for p in B.ROOT.iterdir() if p.is_dir())[6]

#: MAUD 7#.par 的方石英 Delft 参数
MAUD_D = 27.168
MAUD_EPS = 0.016363282

#: 与 eval_shijk_report.COMBO_EXTRA 逐位一致
COMBO_EXTRA = {"po_probe": True, "refine_biso": True, "refine_xyz": True,
               "refine_texture": True, "refine_aniso": True, "refine_eta": True}

ALPHA_CIF = sorted(p for p in B.ROOT.iterdir() if p.is_dir())[3] / \
    "1-cristobalite-Entry_96-900-9688.cif"


def _entry(wavelength: float, d_angstrom: float, eps: float) -> dict:
    """(D, ε) -> Popa LB 各向同性起点（与 forward.aniso_xy 单位互逆）。"""
    y_deg = _RAD2DEG * SCHERRER_K * wavelength / d_angstrom
    x_deg = _RAD2DEG * 4.0 * eps
    return aniso_default(wavelength, x_deg, y_deg)


def full_recipe7(crist_aniso: dict | None = None,
                 swap_alpha: bool = False):
    """样 7 完整配方（复刻 ``bench_v14._full_recipe``，仅改方石英 aniso 起点）。"""
    pat, phases = B._load(7, D7, D7)
    if swap_alpha:
        idx = _crist_index(phases)
        alpha = parse_cif(ALPHA_CIF)
        alpha.name = phases[idx].name
        phases = list(phases)
        phases[idx] = alpha
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    extra = dict(COMBO_EXTRA)
    # 织构初始化：与 _full_recipe 的 po.json 命中逻辑逐位一致
    po = B._read_json("po.json")
    best_axis: dict = {}
    for r in po:
        if (r.get("i") == 7 and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph = r["phase"]
            ax = tuple(int(v) for v in r["axis"])
            if ph not in best_axis or r["delta"] < best_axis[ph][1]:
                best_axis[ph] = (ax, r["delta"])
    if best_axis:
        prm = replace(prm, texture={ph: {"axis": ax,
                                         "grid": default_texture_grid()}
                                    for ph, (ax, _d) in best_axis.items()})
        extra["po_probe"] = False
    if extra.get("refine_aniso"):
        aniso = {st.name: aniso_default(1.5406, 0.0, 0.05) for st in phases}
        if crist_aniso is not None:
            crist = phases[_crist_index(phases)].name
            aniso[crist] = crist_aniso
        prm = replace(prm, aniso=aniso)
    tmin, tmax = 5.0, 120.0
    nbg = max(6, int(round((tmax - tmin) / 6.0)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40)
    cfg = replace(cfg, **extra)
    runner = RecipeRunner()
    t0 = time.time()
    res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
    return res, recs, runner, round(time.time() - t0, 1)


#: 变体表：(标签, D(Å) 或 None, ε, 换 α 相)
VARIANTS: dict[str, tuple[float | None, float, bool]] = {
    "wide_maud": (MAUD_D, MAUD_EPS, False),        # MAUD 同款
    "wide_maud_noeps": (MAUD_D, 0.0, False),       # 只有尺寸宽化
    "wide_50": (50.0, MAUD_EPS, False),
    "wide_strong": (MAUD_D, 0.03, False),
    "alpha_wide": (MAUD_D, MAUD_EPS, True),        # α 相 + 宽包
    "alpha_sharp": (None, 0.0, True),              # α 相窄峰（对照）
}


def main(argv: list[str]) -> int:
    rows_path = OUT / "s7_m8.json"
    rows = json.loads(rows_path.read_text(encoding="utf-8")) \
        if rows_path.exists() else []
    done = {r["label"] for r in rows if r.get("rwp_pct") is not None}
    want = [argv[1]] if len(argv) > 1 else list(VARIANTS)
    for label in want:
        if label not in VARIANTS:
            print(f"未知变体 {label}，可选：{list(VARIANTS)}")
            return 2
        if label in done:
            print(f"[{label}] 已完成，跳过")
            continue
        d_ang, eps, swap = VARIANTS[label]
        entry = None if d_ang is None else _entry(1.5406, d_ang, eps)
        t0 = time.time()
        try:
            res, recs, runner, secs = full_recipe7(
                crist_aniso=entry, swap_alpha=swap)
            crist = None
            for st in (runner.phases or []):
                if "8234" in st.name or "9688" in st.name:
                    crist = st
            row = {"label": label, "d": d_ang, "eps": eps,
                   "swap_alpha": swap, "rwp_pct": None if res is None
                   else round(float(res.rwp), 3),
                   "seconds": round(time.time() - t0, 1)}
            if res is not None:
                raw = [float(p.scale) * float(p.volume) ** 2
                       for p in res.phases]
                tot = sum(raw) or 1.0
                row["qpa"] = [
                    {"name": p.name[:36],
                     "vol_pct": round(100.0 * v / tot, 2)}
                    for p, v in zip(res.phases, raw)]
                row["crist_cell"] = (list(crist.cell) if crist is not None
                                     and crist.cell else None)
            rows.append(row)
            print(f"[{label}] Rwp={row['rwp_pct']}  {row['seconds']}s")
        except Exception as exc:                              # noqa: BLE001
            rows.append({"label": label, "error": f"{type(exc).__name__}: {exc}",
                         "seconds": round(time.time() - t0, 1)})
            print(f"[{label}] 失败：{exc}")
        rows_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
