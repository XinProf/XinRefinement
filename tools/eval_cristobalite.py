"""v1.4 #21：样品 7「无序方石英」结构模型评估。

背景（评估报告 §3.1.2）：样品 7 在 21.9° 有一根孤立强峰（低温方石英
P4₁2₁2 的 (101)），但用户给的 CIF 是高温 Fd-3m，且两种理想多型都拟合
不出 31–37° 的峰形；方石英 wt% 在 4.5 / 6.0 / 35.86 之间乱跳。

本脚本做两组可复现对照：

1. ``models``：增量口径（cell 步精修后的其它 4 相固定、全部非线性关），
   只替换方石英结构 / 完全移除，单次 solve 记录 Rwp 与各相 wt%；
2. ``damp``：在最佳结构模型上固定该相的 ``ΔB_iso``（v1.4 #18 的逐相
   高角衰减），扫描 0–6 Å²。物理含义是「静态无序/微晶」的 Debye–Waller
   式衰减：低角主峰基本保留，高角那批多余强峰被压掉。

输出：``C:\\Temp\\maud_compare\\v14\\crist.json``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                             # noqa: E402
from xinrefinement.core.profile.cif import parse_cif              # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve   # noqa: E402

ROOT = Path(os.environ.get("XR_BENCH_ROOT", r"d:\test_XRD\ShiJK-Refinement"))
OUT = B.OUT
D7 = sorted(p for p in ROOT.iterdir() if p.is_dir())[6]
LOW_S6 = (sorted(p for p in ROOT.iterdir() if p.is_dir())[5]
          / "4-cristobalite-Entry_96-901-7339.cif")
LOW_S4 = (sorted(p for p in ROOT.iterdir() if p.is_dir())[3]
          / "1-cristobalite-Entry_96-900-9688.cif")

#: 样品 7 的方石英相（文件名含 8234）
CRIST_KEY = "8234"
DAMP_B = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0)


def _crist_index(phases) -> int:
    """定位方石英相：优先 source_path，兼容早期缓存（该字段为 None）。

    ``base_7_phases.pkl`` 是 ``source_path`` 落地前生成的，缓存结构里该
    属性为 None；相名本身就带 CIF 编号，故用「路径 ∪ 相名」双判定。
    """
    for j, st in enumerate(phases):
        blob = f"{getattr(st, 'source_path', '') or ''} {st.name}"
        if CRIST_KEY in blob:
            return j
    raise ValueError(f"样品 7 相列表里找不到含 {CRIST_KEY} 的方石英相")


def _weights(res) -> dict:
    return {p.name: (None if p.weight_pct is None else round(float(p.weight_pct), 2))
            for p in res.phases}


def stage_models() -> None:
    """增量口径：cell 步精修后的其它 4 相固定，只换/删方石英结构。

    与 §3.1.2 的「完整配方换模型」不同，这里用单次 solve（全部非线性关）
    做**模型间的相对比较**：快一个数量级，且不受配方链其它步骤的自由度
    重新分配干扰。基准 Rwp 不能与 §11.5 的配方末值直接相减。
    """
    rows = B._read_json("crist_models.json")
    done = {r["model"] for r in rows}
    pat = B._load(7, D7, D7)[0]
    b = B._load_base(7)
    cfg0 = B._only(b["cfg"])
    refined = B._refined_phases(7, D7, D7)
    cases = (
        ("high_T_Fd-3m", None, False),
        ("low_T_s6_P41212", LOW_S6, False),
        ("low_T_s4_P41212", LOW_S4, False),
        ("no_cristobalite", None, True),
    )
    for label, swap, drop in cases:
        if label in done:
            continue
        try:
            phases = list(refined)
            idx = _crist_index(phases)
            crist = phases[idx].name
            if drop:
                phases.pop(idx)
            elif swap is not None:
                st = parse_cif(swap)
                st.name = crist
                phases[idx] = st
            ref = B._delta_baseline(pat, phases, b)
            t0 = time.time()
            res = solve(RefineInputs(pat, phases, b["prm"], cfg0))
            row = {"model": label, "swap": None if swap is None else str(swap),
                   "drop": drop, "crist_phase": crist,
                   "rwp_pct": float(res.rwp), "ref_rwp": ref,
                   "delta": float(res.rwp) - ref,
                   "seconds": round(time.time() - t0, 1),
                   "weights": _weights(res),
                   "warnings": list(res.warnings)[:3]}
        except Exception as exc:                                  # noqa: BLE001
            row = {"model": label, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        B._write_json("crist_models.json", rows)
        print(json.dumps({"stage": "crist_models", "model": label,
                          "rwp_pct": row["rwp_pct"]},
                         ensure_ascii=False), flush=True)


def stage_damp() -> None:
    """增量口径：同一套 cell 步精修晶胞，只改方石英 ΔB_iso。"""
    cached = OUT / "crist_damp.json"
    rows = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else []
    done = {(r["model"], r["b_iso"]) for r in rows}
    for label, swap in (("high_T_Fd-3m", None),
                        ("low_T_s6_P41212", LOW_S6)):
        pat = B._load(7, D7, D7)[0]
        b = B._load_base(7)
        cfg0 = B._only(b["cfg"])
        # 必须用 cell 步精修后的相列表：#20 已证实拿原始 CIF 做增量会让
        # 峰位错乱、Rwp 假劣化 10 pt 以上，全部增量结论失效。
        phases = list(B._refined_phases(7, D7, D7))
        idx = _crist_index(phases)
        crist = phases[idx].name
        if swap is not None:
            st = parse_cif(swap)
            st.name = crist
            phases[idx] = st
        ref_rwp = B._delta_baseline(pat, phases, b)
        for bv in DAMP_B:
            if (label, bv) in done:
                continue
            try:
                prm = replace(b["prm"], b_iso={crist: bv})
                res = solve(RefineInputs(pat, phases, prm, cfg0))
                row = {"model": label, "b_iso": bv,
                       "rwp_pct": float(res.rwp),
                       "delta": float(res.rwp) - ref_rwp,
                       "ref_rwp": ref_rwp,
                       "weights": _weights(res)}
            except Exception as exc:                              # noqa: BLE001
                row = {"model": label, "b_iso": bv, "rwp_pct": None,
                       "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            cached.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(json.dumps({"stage": "crist_damp", "model": label,
                              "b_iso": bv, "rwp_pct": row["rwp_pct"]},
                             ensure_ascii=False), flush=True)


def stage_models_m4m5() -> None:
    """M8 v2：在 M4+M5 口径（Popa LB + EWIMV 织构 + ΔB_iso）下重做多型对照。

    与 :func:`stage_models` 的差别只在非线性层：这里叠加 EWIMV 织构
    （``po.json`` 命中轴）、每相 Popa LB（``aniso_auto``）与每相 ``ΔB_iso``。
    这样既比较各模型的 Rwp，也能看到方石英的 ``ΔB_iso`` 是否**仍在撞
    6 Å² 上界**——撞界说明该相结构仍在替别的模型误差背锅，而不是物理温度
    因子（v1.4 #18 / K7）。
    """
    rows = B._read_json("crist_models_m4m5.json")
    done = {r["model"] for r in rows}
    pat = B._load(7, D7, D7)[0]
    b = B._load_base(7)
    refined = B._refined_phases(7, D7, D7)

    # 织构：沿用 combo 口径（po.json 中增益 > 0.3 pt 的相与轴）
    po = B._read_json("po.json")
    best_axis: dict = {}
    for r in po:
        if (r.get("i") == 7 and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v) for v in r["axis"])
            if ph not in best_axis or r["delta"] < best_axis[ph][1]:
                best_axis[ph] = (ax, r["delta"])
    from xinrefinement.core.profile.forward import default_texture_grid
    tex = {ph: {"axis": ax, "grid": default_texture_grid()}
           for ph, (ax, _d) in best_axis.items()}
    prm0 = replace(b["prm"], texture=(tex or None), aniso=None)
    cfg0 = B._only(b["cfg"], refine_texture=True, refine_aniso=True,
                   refine_biso=True, max_iter=25, aniso_auto=True)

    cases = (
        ("high_T_Fd-3m", None, False),
        ("low_T_s6_P41212", LOW_S6, False),
        ("low_T_s4_P41212", LOW_S4, False),
        ("no_cristobalite", None, True),
    )
    for label, swap, drop in cases:
        if label in done:
            continue
        try:
            phases = list(refined)
            idx = _crist_index(phases)
            crist = phases[idx].name
            if drop:
                phases.pop(idx)
            elif swap is not None:
                st = parse_cif(swap)
                st.name = crist
                phases[idx] = st
            t0 = time.time()
            res = solve(RefineInputs(pat, phases, prm0, cfg0))
            biso = {k: round(float(v), 4) for k, v in (res.params.b_iso or {}).items()}
            row = {"model": label, "swap": None if swap is None else str(swap),
                   "drop": drop, "crist_phase": crist,
                   "rwp_pct": float(res.rwp),
                   "seconds": round(time.time() - t0, 1),
                   "biso": biso,
                   "crist_biso_hit_bound": bool(
                       crist in biso and biso[crist] >= 5.99),
                   "weights": _weights(res),
                   "warnings": [w for w in res.warnings
                                if "Popa LB（" in w][:6]}
        except Exception as exc:                                  # noqa: BLE001
            row = {"model": label, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        B._write_json("crist_models_m4m5.json", rows)
        print(json.dumps({"stage": "crist_models_m4m5", "model": label,
                          "rwp_pct": row["rwp_pct"],
                          "crist_hit": row.get("crist_biso_hit_bound")},
                         ensure_ascii=False), flush=True)


def main(argv: list[str]) -> int:
    stage = argv[1] if len(argv) > 1 else "models"
    {"models": stage_models, "damp": stage_damp,
     "models_m4m5": stage_models_m4m5}[stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
