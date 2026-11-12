"""v1.4 #20：7 实样对拍复测（v1.3 引擎能力增量评估）。

与 v1.2 时代的 ``C:\\Temp\\maud_compare\\afterfix_tent.py`` 同口径：
谱图 5–90°、tent 自适应 14 节点、integrated=True、Cu Kα、标准配方连跑。
本脚本在**当前 HEAD** 上重建基线，并在收敛参数上做「增量单次 solve」，
度量 v1.3 新能力的边际收益（不重复跑整条配方链，节省一个数量级时间）。

分阶段执行（每阶段增量落盘，可断点续跑）::

    python tools/bench_v14.py base     # 7 样完整配方 → base_N.pkl + base.json
    python tools/bench_v14.py po       # 每相 × 候选轴 的 MD-r 试探 → po.json
    python tools/bench_v14.py tex      # 最佳轴单相 EWIMV 织构 → tex.json
    python tools/bench_v14.py mur      # 按成分算 μ·r → QPA 修正表 → mur.json
    python tools/bench_v14.py probe    # 完整配方 + PO 自动试探 → probe.json
    python tools/bench_v14.py win      # 窗口 5–120° 完整配方 → win.json
    python tools/bench_v14.py aniso    # 样品 5 Popa LB 增量 → aniso.json
    python tools/bench_v14.py biso_inc   # #18 7 样轻量增量 ΔB_iso → biso_inc.json
    python tools/bench_v14.py biso 1,3,7 # #18 完整配方 + B 步 → biso.json
    python tools/bench_v14.py xyz 1,3,7  # #17 完整配方 + xyz 步 → xyz.json
    python tools/bench_v14.py combo 1,3  # 全增益叠加口径 → combo.json

输出目录：``C:\\Temp\\maud_compare\\v14``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xinrefinement.core.absorption import calc_microabs, calc_mu_r   # noqa: E402
from xinrefinement.core.patterns import load_pattern                  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif                  # noqa: E402
from xinrefinement.core.profile.forward import (                     # noqa: E402
    ProfileParams, brindley_factor, default_texture_grid)
from xinrefinement.core.refine.nonlinear import RefineConfig           # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner              # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve        # noqa: E402

#: 数据集根可用环境变量覆盖（2026-11-12 数据集迁到 d:\test_XRD，旧盘符已不存在）。
ROOT = Path(os.environ.get("XR_BENCH_ROOT", r"d:\test_XRD\ShiJK-Refinement"))
#: 样 5 的相文件不在样目录内，单独放在 MAUD 侧目录；缺该目录时样 5 无法对标。
S5PHASE = Path(os.environ.get("XR_BENCH_S5PHASE",
                              r"C:\Temp\maud_compare\s5phase"))
OUT = Path(os.environ.get("XR_BENCH_OUT", r"C:\Temp\maud_compare\v14"))
OUT.mkdir(parents=True, exist_ok=True)

#: MD 候选织构轴（低指数，覆盖常见纤维织构；负值等价，取 |cos| 折返）
PO_AXES = ((0, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))
#: μ·r 参考晶粒半径（μm）——微吸收校正的唯一自由输入，取常见粉体量级
GRAIN_UM = 5.0


def sample_dirs() -> list[tuple[int, Path, Path]]:
    out = []
    for i, d in enumerate(sorted(p for p in ROOT.iterdir() if p.is_dir()), 1):
        # 样 5 的相文件原先单独放在 MAUD 侧目录；该目录不存在时（2026-11-12 起
        # CIF 已并入样本目录）直接用样本目录，避免拿到空相表。
        pdir = S5PHASE if (i == 5 and S5PHASE.is_dir()) else d
        out.append((i, d, pdir))
    return out


def _load(i: int, d: Path, pdir: Path):
    return (load_pattern(next(d.glob("*.txt"))),
            [parse_cif(c) for c in sorted(pdir.glob("*.cif"))])


def _base_inputs(i: int, d: Path, pdir: Path):
    pat, phases = _load(i, d, pdir)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    nbg = max(6, int(round((90.0 - 5.0) / 6.0)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=5.0, tmax=90.0, max_iter=40)
    return pat, phases, prm, cfg


def _only(cfg: RefineConfig, **kw) -> RefineConfig:
    """关闭全部非线性开关后按 kw 打开；保留背景/窗口/σ 等设置。"""
    off = dict(refine_zero=False, refine_uvw=False, refine_eta=False,
               refine_asym=False, refine_bfactor=False, refine_cell=False,
               refine_po=False, refine_size=False, refine_strain=False,
               refine_texture=False, refine_aniso=False,
               refine_biso=False, refine_xyz=False,
               refine_microabs=False, po_probe=False)
    off.update(kw)
    return replace(cfg, **off)


def _read_json(name: str) -> list:
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _write_json(name: str, rows: list) -> None:
    (OUT / name).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_base(i: int, res, phases=None) -> None:
    with (OUT / f"base_{i}.pkl").open("wb") as fh:
        pickle.dump({"rwp": float(res.rwp), "prm": res.params,
                     "phases": phases,
                     "cfg": res.config, "phase_infos": res.phases,
                     "weights": [(p.name, None if p.weight_pct is None
                                  else float(p.weight_pct)) for p in res.phases],
                     "scales": [float(s) for s in res.engine.scales],
                     "warnings": list(res.warnings)}, fh)


def _load_base(i: int) -> dict:
    with (OUT / f"base_{i}.pkl").open("rb") as fh:
        return pickle.load(fh)


def _refined_phases(i: int, d: Path, pdir: Path) -> list:
    """取配方 cell 步**精修后**的相列表（旧 base_N.pkl 未存相对象时重建）。

    早期版本只有 prm/cfg，没有保存 ``RecipeRunner.phases``；直接用原始
    CIF 重跑增量 solve 会丢掉精修晶胞（实测样品 1 Rwp 23.88 → 34.74，
    全部增量结论失效）。这里以基线参数对原始 CIF 只做一次全晶胞精修，
    得到与配方等价的相列表并缓存，供 po/tex/aniso 各阶段共用。
    """
    cache = OUT / f"base_{i}_phases.pkl"
    if cache.exists():
        with cache.open("rb") as fh:
            return pickle.load(fh)
    from xinrefinement.core.refine.cell import (
        refine_cell_full, structure_with_cell)

    b = _load_base(i)
    stored = b.get("phases")
    # 旧版 pickle 的 "phases" 是 SolveResult.phases（PhaseInfo，非结构）：
    # 必须用 CifStructure 才能进前向模型，类型不符时走重建。
    if stored and all(hasattr(st, "atoms") for st in stored):
        return stored
    pat, phases = _load(i, d, pdir)
    cfg = _only(b["cfg"])
    mask = ((pat.two_theta >= cfg.tmin) & (pat.two_theta <= cfg.tmax))
    clip = replace(pat, two_theta=pat.two_theta[mask],
                   intensity=pat.intensity[mask])
    cr = refine_cell_full(phases, clip, b["prm"], cfg,
                          backend=b["cfg"].backend)
    out = [structure_with_cell(st, cell)
           for st, cell in zip(phases, cr.cells)]
    with cache.open("wb") as fh:
        pickle.dump(out, fh)
    return out


def _delta_baseline(pat, phases, b: dict) -> float:
    """增量实验自己的对照 Rwp（同一套精修晶胞、全部非线性关）。"""
    return float(solve(RefineInputs(pat, phases, b["prm"],
                                    _only(b["cfg"]))).rwp)


# ---------------------------------------------------------------- stages

def stage_base(want: set[int]) -> None:
    rows = _read_json("base.json")
    done = {r["i"] for r in rows if r.get("rwp_pct") is not None}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            pat, phases, prm, cfg = _base_inputs(i, d, pdir)
            t0 = time.time()
            runner = RecipeRunner()
            res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
            if res is None:
                raise RuntimeError("配方无结果")
            _save_base(i, res, list(runner.phases or phases))
            row = {"i": i, "sample": d.name, "rwp_pct": float(res.rwp),
                   "rexp_pct": float(res.rexp),
                   "seconds": round(time.time() - t0, 1),
                   "weights": [(p.name, None if p.weight_pct is None
                                else float(p.weight_pct)) for p in res.phases],
                   "steps": [(r.key, r.status, r.rwp_after) for r in recs]}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("base.json", rows)
        print(json.dumps({"stage": "base", "i": i,
                          "rwp_pct": row["rwp_pct"]}, ensure_ascii=False),
              flush=True)


def stage_po(want: set[int]) -> None:
    rows = _read_json("po.json")
    done = {(r["i"], r["phase"], str(r["axis"])) for r in rows}
    for i, d, pdir in sample_dirs():
        if want and i not in want:
            continue
        if not (OUT / f"base_{i}.pkl").exists():
            continue
        pat = _load(i, d, pdir)[0]
        phases = _refined_phases(i, d, pdir)
        b = _load_base(i)
        prm0, cfg0 = b["prm"], b["cfg"]
        delta_base = _delta_baseline(pat, phases, b)
        for st in phases:
            for axis in PO_AXES:
                key = (i, st.name, str(axis))
                if key in done:
                    continue
                try:
                    prm = replace(prm0, po_r={st.name: (*axis, 1.0)})
                    cfg = _only(cfg0, refine_po=True, max_iter=12)
                    res = solve(RefineInputs(pat, phases, prm, cfg))
                    row = {"i": i, "phase": st.name, "axis": list(axis),
                           "rwp_pct": float(res.rwp),
                           "delta": float(res.rwp) - delta_base,
                           "delta_base": delta_base,
                           "r": (None if not res.params.po_r
                                 else float(res.params.po_r[st.name][3])),
                           "success": bool(res.success)}
                except Exception as exc:                          # noqa: BLE001
                    row = {"i": i, "phase": st.name, "axis": list(axis),
                           "rwp_pct": None,
                           "error": f"{type(exc).__name__}: {exc}"}
                rows.append(row)
                _write_json("po.json", rows)
                done.add(key)
        got = [r for r in rows if r["i"] == i and r.get("delta") is not None]
        if got:
            best = min(got, key=lambda r: r["delta"])
            print(json.dumps({"stage": "po", "i": i,
                              "best": best["phase"], "axis": best["axis"],
                              "rwp_pct": best["rwp_pct"],
                              "delta": round(best["delta"], 3)},
                             ensure_ascii=False), flush=True)


def stage_tex(want: set[int]) -> None:
    """取 po 阶段每样最优 (相, 轴)，单开 EWIMV 19 点织构做增量精修。"""
    po = _read_json("po.json")
    rows = _read_json("tex.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if want and i not in want or i in done:
            continue
        cand = [r for r in po if r["i"] == i and r.get("delta") is not None]
        if not cand or not (OUT / f"base_{i}.pkl").exists():
            continue
        best = min(cand, key=lambda r: r["delta"])
        try:
            pat = _load(i, d, pdir)[0]
            phases = _refined_phases(i, d, pdir)
            b = _load_base(i)
            delta_base = _delta_baseline(pat, phases, b)
            name = best["phase"]
            tex = {name: {"axis": tuple(best["axis"]),
                          "grid": default_texture_grid()}}
            prm = replace(b["prm"], texture=tex)
            cfg = _only(b["cfg"], refine_texture=True, max_iter=20)
            t0 = time.time()
            res = solve(RefineInputs(pat, phases, prm, cfg))
            grid = ([float(v) for v in
                     (res.params.texture or {}).get(name, {}).get("grid", [])])
            row = {"i": i, "phase": name, "axis": best["axis"],
                   "rwp_pct": float(res.rwp),
                   "delta": float(res.rwp) - delta_base,
                   "delta_base": delta_base,
                   "seconds": round(time.time() - t0, 1),
                   "grid": grid, "warnings": list(res.warnings)[:3],
                   "success": bool(res.success)}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "phase": best["phase"], "axis": best["axis"],
                   "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("tex.json", rows)
        print(json.dumps({"stage": "tex", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_mur(want: set[int]) -> None:
    """按成分计算 μ·r，解析给出 QPA 校正后 wt%（Rwp 简并不变，无需重拟合）。

    校正公式：加入 Brindley 因子 f_p 后精修标度 A'_p = A_p / f_p，
    故 w'_p ∝ (w_p / f_p)（再归一化）。
    """
    rows = _read_json("mur.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if want and i not in want or i in done:
            continue
        _pat, phases = _load(i, d, pdir)
        b = _load_base(i) if (OUT / f"base_{i}.pkl").exists() else None
        per_phase = []
        for st in phases:
            try:
                mu = calc_mu_r(st, GRAIN_UM, anode="Cu")
                per_phase.append({"phase": st.name, "mur": round(mu["mur"], 5),
                                  "mu_cm": round(mu["mu_cm"], 1),
                                  "density": round(mu["density"], 3),
                                  "mu_rho": round(mu["mu_rho"], 1),
                                  "density_source": mu["density_source"],
                                  "warning": mu["warning"]})
            except Exception as exc:                              # noqa: BLE001
                per_phase.append({"phase": st.name,
                                  "error": f"{type(exc).__name__}: {exc}"})
        by_name = {r["phase"]: r for r in per_phase}
        wt = dict(b["weights"]) if b else {}
        corrected = {}
        if wt and all(v is not None for v in wt.values()):
            raw = {}
            for name, w in wt.items():
                info = by_name.get(name)
                f = (brindley_factor(info["mur"])
                     if info and "mur" in info else 1.0)
                raw[name] = w / f if f > 0 else w
            tot = sum(raw.values())
            if tot > 0:
                corrected = {k: round(100.0 * v / tot, 2)
                             for k, v in raw.items()}
        row = {"i": i, "sample": d.name, "grain_um": GRAIN_UM,
               "base_wt": {k: (None if v is None else round(v, 2))
                           for k, v in wt.items()},
               "corrected_wt": corrected, "phases": per_phase}
        rows.append(row)
        _write_json("mur.json", rows)
        print(json.dumps({"stage": "mur", "i": i,
                          "n_ok": sum(1 for r in per_phase if "mur" in r)},
                         ensure_ascii=False), flush=True)


def stage_probe(want: set[int]) -> None:
    """v1.4 #19：完整配方 + micro 步 PO 自动试探，实测 7 样收益。"""
    rows = _read_json("probe.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if want and i not in want or i in done:
            continue
        try:
            pat, phases, prm, cfg = _base_inputs(i, d, pdir)
            cfg = replace(cfg, po_probe=True, po_probe_min_gain=0.3,
                          po_probe_max_phases=2, po_probe_max_iter=12)
            runner = RecipeRunner()
            t0 = time.time()
            res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
            b = _load_base(i)["rwp"] if (OUT / f"base_{i}.pkl").exists() else None
            best = sorted((r for r in runner.po_probe_report
                           if r.get("gain") is not None),
                          key=lambda r: -r["gain"])[:3]
            row = {"i": i, "sample": d.name,
                   "rwp_pct": None if res is None else float(res.rwp),
                   "delta": (None if res is None or b is None
                             else float(res.rwp) - b),
                   "seconds": round(time.time() - t0, 1),
                   "po_r": ({k: list(v) for k, v in res.params.po_r.items()}
                            if res is not None and res.params.po_r else {}),
                   "best_probes": best,
                   "micro_message": recs[-1].message if recs else ""}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("probe.json", rows)
        print(json.dumps({"stage": "probe", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_win(want: set[int]) -> None:
    """v1.4 #19：窗口放开到 5–120°（谱图原始范围），节点数按跨度自适应。"""
    rows = _read_json("win.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if want and i not in want or i in done:
            continue
        try:
            pat, phases = _load(i, d, pdir)
            prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                                anode="Cu", integrated=True)
            tmin, tmax = 5.0, 120.0
            nbg = max(6, int(round((tmax - tmin) / 6.0)))
            cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                               bg_mode="tent", tmin=tmin, tmax=tmax,
                               max_iter=40)
            runner = RecipeRunner()
            t0 = time.time()
            res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
            b = _load_base(i)["rwp"] if (OUT / f"base_{i}.pkl").exists() else None
            row = {"i": i, "sample": d.name, "tmax": tmax, "n_bg": nbg,
                   "rwp_pct": None if res is None else float(res.rwp),
                   "delta_90": (None if res is None or b is None
                                else float(res.rwp) - b),
                   "seconds": round(time.time() - t0, 1),
                   "steps": [(r.key, r.status, r.rwp_after) for r in recs]}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("win.json", rows)
        print(json.dumps({"stage": "win", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta_90": row.get("delta_90")},
                         ensure_ascii=False), flush=True)


def stage_aniso(want: set[int]) -> None:
    """v1.3 #15 在实样上的边际收益：从基线参数单开 Popa LB 尺寸精修。

    只测报告 §4.6 点名的样品 5（石英窄峰 / 高岭石宽峰）；其余样默认跳过。
    """
    from xinrefinement.core.profile.forward import aniso_default

    rows = _read_json("aniso.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if i not in (want or {5}) or i in done:
            continue
        if not (OUT / f"base_{i}.pkl").exists():
            continue
        try:
            pat = _load(i, d, pdir)[0]
            phases = _refined_phases(i, d, pdir)
            b = _load_base(i)
            delta_base = _delta_baseline(pat, phases, b)
            wl = 1.5406
            aniso = {st.name: aniso_default(wl, 0.0, 0.05) for st in phases}
            prm = replace(b["prm"], aniso=aniso)
            cfg = _only(b["cfg"], refine_aniso=True, max_iter=25)
            t0 = time.time()
            res = solve(RefineInputs(pat, phases, prm, cfg))
            row = {"i": i, "rwp_pct": float(res.rwp),
                   "delta": float(res.rwp) - delta_base,
                   "delta_base": delta_base,
                   "seconds": round(time.time() - t0, 1),
                   "warnings": list(res.warnings)[:3],
                   "success": bool(res.success)}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("aniso.json", rows)
        print(json.dumps({"stage": "aniso", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": row.get("delta")},
                         ensure_ascii=False), flush=True)


def _full_recipe(i: int, d: Path, pdir: Path, extra: dict,
                 tmax: float = 90.0):
    """v1.4 端到端口径：与 base 同样的配方链，只改 cfg 开关/窗口。"""
    pat, phases = _load(i, d, pdir)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    # P1 试验：refine_texture 时从 po.json 命中轴自动初始化 EWIMV 织构
    # （每相一个 axis + 19 点 default grid），让 EWIMV 在组合口径真正精修。
    if extra.get("refine_texture"):
        po = _read_json("po.json")
        best_axis: dict = {}
        for r in po:
            if (r.get("i") == i and r.get("delta") is not None
                    and r["delta"] < -0.3 and r.get("axis")):
                ph = r["phase"]
                ax = tuple(int(v) for v in r["axis"])
                if ph not in best_axis or r["delta"] < best_axis[ph][1]:
                    best_axis[ph] = (ax, r["delta"])
        if best_axis:
            prm = replace(prm, texture={ph: {"axis": ax,
                                            "grid": default_texture_grid()}
                                        for ph, (ax, _d) in best_axis.items()})
            # P1/T25：有织构相用 EWIMV 替代 MD PO，关闭 po_probe 避免两者
            # 并存稀释 EWIMV 增益（EWIMV 是 MD 的一般化形式）
            extra = {**extra, "po_probe": False}
    if extra.get("refine_aniso"):
        from xinrefinement.core.profile.forward import aniso_default
        prm = replace(prm, aniso={st.name: aniso_default(1.5406, 0.0, 0.05)
                                  for st in phases})
    tmin = 5.0
    if i == 5:  # 样 5b 数据仅 10–100°，禁止按 5–120° 外推（MAUD 也用数据全谱）
        tmin, tmax = 10.0, 100.0
    nbg = max(6, int(round((tmax - tmin) / 6.0)))
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=nbg,
                       bg_mode="tent", tmin=tmin, tmax=tmax, max_iter=40)
    cfg = replace(cfg, **extra)
    runner = RecipeRunner()
    t0 = time.time()
    res, recs = runner.run_all(RefineInputs(pat, phases, prm, cfg))
    return res, recs, runner, round(time.time() - t0, 1)


def _base_rwp(i: int) -> float | None:
    p = OUT / f"base_{i}.pkl"
    return _load_base(i)["rwp"] if p.exists() else None


def _stage_full(name: str, want: set[int], extra: dict,
                tmax: float = 90.0, pick=None) -> None:
    """完整配方 + 开关组合的通用阶段（逐样增量落盘，可断点续跑）。"""
    rows = _read_json(f"{name}.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            res, recs, runner, secs = _full_recipe(i, d, pdir, extra, tmax)
            if res is None:
                raise RuntimeError("配方无结果")
            b = _base_rwp(i)
            row = {"i": i, "sample": d.name, "tmax": tmax,
                   "rwp_pct": float(res.rwp),
                   "delta": (None if b is None else float(res.rwp) - b),
                   "seconds": secs,
                   "steps": [(r.key, r.status, r.rwp_after, r.message[:120])
                             for r in recs]}
            if pick:
                row.update(pick(res, recs, runner))
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json(f"{name}.json", rows)
        print(json.dumps({"stage": name, "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_biso_inc(want: set[int]) -> None:
    """v1.4 #18 轻量增量：同一套精修晶胞 + 全关非线性，只放开逐相 ΔB_iso。

    与 po/tex/aniso 阶段完全同口径（``_delta_baseline``），单次 solve，
    7 样全量可在数分钟内跑完；完整配方端到端由 ``biso`` 阶段在差距样上补。
    """
    rows = _read_json("biso_inc.json")
    done = {r["i"] for r in rows}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        if not (OUT / f"base_{i}.pkl").exists():
            continue
        try:
            pat = _load(i, d, pdir)[0]
            phases = _refined_phases(i, d, pdir)
            b = _load_base(i)
            ref = _delta_baseline(pat, phases, b)
            cfg = _only(b["cfg"], refine_biso=True, max_iter=25)
            t0 = time.time()
            res = solve(RefineInputs(pat, phases, b["prm"], cfg))
            row = {"i": i, "sample": d.name, "rwp_pct": float(res.rwp),
                   "delta": float(res.rwp) - ref, "ref_rwp": ref,
                   "seconds": round(time.time() - t0, 1),
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "warnings": list(res.warnings)[:3],
                   "success": bool(res.success)}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("biso_inc.json", rows)
        print(json.dumps({"stage": "biso_inc", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_biso(want: set[int]) -> None:
    """v1.4 #18：完整配方开启 B 步（逐相 ΔB_iso），实测端到端收益。

    重型阶段：建议只跑差距样 ``1,3,7``；7 样轻量口径见 ``biso_inc``。
    """
    def pick(res, recs, runner):
        bstep = next((r for r in recs if r.key == "B"), None)
        return {"biso": {k: round(float(v), 4)
                         for k, v in (res.params.b_iso or {}).items()},
                "b_step": (None if bstep is None else
                           {"status": bstep.status,
                            "rwp_before": bstep.rwp_before,
                            "rwp_after": bstep.rwp_after})}
    _stage_full("biso", want, {"refine_biso": True}, pick=pick)


def stage_xyz(want: set[int]) -> None:
    """v1.4 #17：完整配方开启 xyz 步（Wyckoff 位约束），实测 7 样端到端收益。"""
    def pick(res, recs, runner):
        xstep = next((r for r in recs if r.key == "xyz"), None)
        return {"xyz_report": runner.xyz_report,
                "xyz_step": (None if xstep is None else
                             {"status": xstep.status,
                              "message": xstep.message,
                              "rwp_before": xstep.rwp_before,
                              "rwp_after": xstep.rwp_after}),
                "weights": [(p.name, None if p.weight_pct is None
                             else float(p.weight_pct)) for p in res.phases]}
    _stage_full("xyz", want, {"refine_xyz": True}, pick=pick)


def stage_combo(want: set[int]) -> None:
    """v1.4 推荐口径叠加：5–120° + PO 试探 + B 步 + xyz 步。

    与同窗口的 win 阶段对照可分离「窗口收益」与「建模收益」。
    """
    rows = _read_json("combo.json")
    done = {r["i"] for r in rows}
    win = {r["i"]: r.get("rwp_pct") for r in _read_json("win.json")}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            extra = {"po_probe": True, "refine_biso": True,
                     "refine_xyz": True}
            res, recs, runner, secs = _full_recipe(i, d, pdir, extra, 120.0)
            if res is None:
                raise RuntimeError("配方无结果")
            b, w = _base_rwp(i), win.get(i)
            row = {"i": i, "sample": d.name, "tmax": 120.0,
                   "rwp_pct": float(res.rwp),
                   "delta": (None if b is None else float(res.rwp) - b),
                   "delta_win": (None if w is None else float(res.rwp) - w),
                   "seconds": secs,
                   "po_r": ({k: list(v) for k, v in res.params.po_r.items()}
                            if res.params.po_r else {}),
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "xyz_report": runner.xyz_report,
                   "steps": [(r.key, r.status, r.rwp_after, r.message[:120])
                             for r in recs]}
        except Exception as exc:                                  # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("combo.json", rows)
        print(json.dumps({"stage": "combo", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_combo_tex(want: set[int]) -> None:
    """P1 试验：combo 口径再叠加 EWIMV 织构（refine_texture=True，默认
    texture_lambda=1.0 二阶差分光滑罚），量化 EWIMV 在组合里的真实增益
    与过拟合风险（Delta B_iso 是否撞 6 A^2 上界）。"""
    rows = _read_json("combo_tex.json")
    done = {r["i"] for r in rows}
    win = {r["i"]: r.get("rwp_pct") for r in _read_json("win.json")}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            extra = {"po_probe": True, "refine_biso": True,
                     "refine_xyz": True, "refine_texture": True}
            res, recs, runner, secs = _full_recipe(i, d, pdir, extra, 120.0)
            if res is None:
                raise RuntimeError("配方无结果")
            b, w = _base_rwp(i), win.get(i)
            row = {"i": i, "sample": d.name, "tmax": 120.0,
                   "rwp_pct": float(res.rwp),
                   "delta": (None if b is None else float(res.rwp) - b),
                   "delta_win": (None if w is None else float(res.rwp) - w),
                   "seconds": secs,
                   "po_r": ({k: list(v) for k, v in res.params.po_r.items()}
                            if res.params.po_r else {}),
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "texture": ({k: [round(float(x), 3) for x in v.get("grid", [])]
                                for k, v in (res.params.texture or {}).items()}),
                   "xyz_report": runner.xyz_report,
                   "steps": [(r.key, r.status, r.rwp_after, r.message[:120])
                             for r in recs]}
        except Exception as exc:                                          # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("combo_tex.json", rows)
        print(json.dumps({"stage": "combo_tex", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_combo_tex_aniso(want: set[int]) -> None:
    """P1 试验：combo+EWIMV 再叠加 Popa LB 各向异性展宽 + eta 峰形细化，
    定位样 1 距 15% 的最后约 1 pt 缺口是否来自微结构各向异性/峰形。"""
    rows = _read_json("combo_tex_aniso.json")
    done = {r["i"] for r in rows}
    win = {r["i"]: r.get("rwp_pct") for r in _read_json("win.json")}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            extra = {"po_probe": True, "refine_biso": True,
                     "refine_xyz": True, "refine_texture": True,
                     "refine_aniso": True, "refine_eta": True}
            res, recs, runner, secs = _full_recipe(i, d, pdir, extra, 120.0)
            if res is None:
                raise RuntimeError("配方无结果")
            b, w = _base_rwp(i), win.get(i)
            row = {"i": i, "sample": d.name, "tmax": 120.0,
                   "rwp_pct": float(res.rwp),
                   "delta": (None if b is None else float(res.rwp) - b),
                   "delta_win": (None if w is None else float(res.rwp) - w),
                   "seconds": secs,
                   "po_r": ({k: list(v) for k, v in res.params.po_r.items()}
                            if res.params.po_r else {}),
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "texture": ({k: [round(float(x), 3) for x in v.get("grid", [])]
                                for k, v in (res.params.texture or {}).items()}),
                   "xyz_report": runner.xyz_report,
                   "steps": [(r.key, r.status, r.rwp_after, r.message[:120])
                             for r in recs]}
        except Exception as exc:                                          # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("combo_tex_aniso.json", rows)
        print(json.dumps({"stage": "combo_tex_aniso", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def stage_combo_interp(want: set[int]) -> None:
    """P1 试验：combo+EWIMV 改用 MAUD 式插值背景（bg_mode=interp，
    n_bg≈12 对齐 MAUD interpolation_range 10，bg_interp_iters=10 默认）。"""
    rows = _read_json("combo_interp.json")
    done = {r["i"] for r in rows}
    win = {r["i"]: r.get("rwp_pct") for r in _read_json("win.json")}
    for i, d, pdir in sample_dirs():
        if (want and i not in want) or i in done:
            continue
        try:
            extra = {"po_probe": True, "refine_biso": True,
                     "refine_xyz": True, "refine_texture": True,
                     "bg_mode": "interp", "n_bg": 12}
            res, recs, runner, secs = _full_recipe(i, d, pdir, extra, 120.0)
            if res is None:
                raise RuntimeError("配方无结果")
            b, w = _base_rwp(i), win.get(i)
            row = {"i": i, "sample": d.name, "tmax": (100.0 if i == 5 else 120.0),
                   "rwp_pct": float(res.rwp),
                   "delta": (None if b is None else float(res.rwp) - b),
                   "delta_win": (None if w is None else float(res.rwp) - w),
                   "seconds": secs,
                   "biso": {k: round(float(v), 4)
                            for k, v in (res.params.b_iso or {}).items()},
                   "steps": [(s.key, s.status, s.rwp_after) for s in recs]}
        except Exception as exc:                                          # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        _write_json("combo_interp.json", rows)
        print(json.dumps({"stage": "combo_interp", "i": i,
                          "rwp_pct": row["rwp_pct"],
                          "delta": (None if row.get("delta") is None
                                    else round(row["delta"], 3))},
                         ensure_ascii=False), flush=True)


def main(argv: list[str]) -> int:
    stage = argv[1] if len(argv) > 1 else "base"
    want = {int(x) for x in argv[2].split(",")} if len(argv) > 2 else set()
    {"base": stage_base, "po": stage_po, "tex": stage_tex,
     "mur": stage_mur, "probe": stage_probe, "win": stage_win,
     "aniso": stage_aniso, "biso": stage_biso, "biso_inc": stage_biso_inc,
     "xyz": stage_xyz, "combo": stage_combo, "combo_tex": stage_combo_tex,
     "combo_tex_aniso": stage_combo_tex_aniso,
     "combo_interp": stage_combo_interp}[stage](want)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
