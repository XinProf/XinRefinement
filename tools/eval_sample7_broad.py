"""v1.5 M8 深化：样 7 方石英「近非晶宽包」增量验证（只读实验，不改产品代码）。

背景
----
MAUD ``7#.par`` 对该样的 Cristobalite（β, Fd-3m）用的是 **Delft Isotropic**
尺寸应变模型，参数为

    _riet_par_cryst_size    27.168 Å      （纳米晶，宽包）
    _riet_par_rs_microstrain 0.01636     （1.6% 微应变）
    _pd_proc_ls_pref_orient_corr  "none tex"

换句话说，MAUD 并没有把方石英当正常晶体拟合，而是用「β 相 + 极宽化」
去吸收 21.9° 附近那根无序/纳米方石英的包。M8 已证实换成 α 相能到
15.357（完整配方），但仍差 MAUD 4.06 pt。

我们这边的 ``aniso``（Popa LB）边界 ``ANISO_SIZE_BOUNDS=(1e-4,1.6)`` /
``ANISO_STRAIN_BOUNDS=(1e-6,0.1)`` 其实**够得着** MAUD 的参数
（inv_D = 0.0368 Å⁻¹、ε = 0.0164），但配方起点是
``aniso_default(λ, 0.0, 0.05)``——inv_D 仅 6.3e-4，差 58 倍，LM 的
数值雅可比很难从窄峰起点走到宽包。

本脚本用增量口径（cell 步精修晶胞 + 全部非线性关）做纯前向对照：
只给方石英相挂一份各向同性宽包 ``aniso``，其它相完全不动，观察 Rwp。
若宽包能显著降低 Rwp，就说明样 7 剩余缺口的主体是**起点/局部极小**，
下一步应做「逐相尺寸应变起点自适应」，而不是继续调织构或峰形。

用法::

    python tools/eval_sample7_broad.py            # 扫 D（ε 固定 MAUD 值）
    python tools/eval_sample7_broad.py strain    # 扫 ε（D 固定 MAUD 值）
    python tools/eval_sample7_broad.py alpha     # 上述最优 + α 相组合

输出 ``C:\\Temp\\maud_compare\\v14\\s7_broad.json``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                             # noqa: E402
from eval_cristobalite import _crist_index, LOW_S4, LOW_S6        # noqa: E402
from xinrefinement.core.profile.cif import parse_cif              # noqa: E402
from xinrefinement.core.profile.forward import (                  # noqa: E402
    _RAD2DEG, SCHERRER_K, aniso_default)
from xinrefinement.core.refine.solve import RefineInputs, solve   # noqa: E402

OUT = B.OUT
D7 = sorted(p for p in B.ROOT.iterdir() if p.is_dir())[6]

#: MAUD 7#.par 的方石英 Delft 参数
MAUD_D = 27.168
MAUD_EPS = 0.016363282

#: 扫描网格（D 单位 Å；None = 不挂 aniso，即纯标量窄峰基准）
D_GRID = (None, 200.0, 100.0, 50.0, MAUD_D, 15.0, 8.0)
EPS_GRID = (0.0, 0.005, MAUD_EPS, 0.03, 0.06)


def _entry(wavelength: float, d_angstrom: float | None, eps: float) -> dict | None:
    """把 (D, ε) 转成 Popa LB 各向同性起点，单位与 forward.aniso_xy 严格互逆。"""
    if d_angstrom is None:
        return None
    y_deg = _RAD2DEG * SCHERRER_K * wavelength / d_angstrom
    x_deg = _RAD2DEG * 4.0 * eps
    return aniso_default(wavelength, x_deg, y_deg)


def _run(label: str, d_angstrom: float | None, eps: float,
         swap: Path | None, rows: list) -> None:
    key = (label, swap.name if swap else "beta")
    if any(r.get("label") == key[0] and r.get("cif") == key[1]
           and r.get("d") == d_angstrom and r.get("eps") == eps
           and r.get("rwp_pct") is not None for r in rows):
        return
    try:
        pat = B._load(7, D7, D7)[0]
        b = B._load_base(7)
        cfg0 = B._only(b["cfg"])
        phases = list(B._refined_phases(7, D7, D7))
        idx = _crist_index(phases)
        crist = phases[idx].name
        if swap is not None:
            st = parse_cif(swap)
            st.name = crist
            phases[idx] = st

        prm = b["prm"]
        entry = _entry(float(prm.wavelength), d_angstrom, eps)
        if entry is None:
            prm = replace(prm, aniso=None)
        else:
            # 只给方石英挂宽包；其它相 aniso 缺失 -> 继续用标量 X/Y（=0）
            prm = replace(prm, aniso={crist: entry})
        ref = B._delta_baseline(pat, phases, b)
        t0 = time.time()
        res = solve(RefineInputs(pat, phases, prm, cfg0))
        row = {"label": label, "cif": key[1], "d": d_angstrom, "eps": eps,
               "rwp_pct": float(res.rwp), "ref_rwp": ref,
               "delta": float(res.rwp) - ref,
               "seconds": round(time.time() - t0, 1),
               "weights": {p.name: (None if p.weight_pct is None
                                    else round(float(p.weight_pct), 2))
                           for p in res.phases}}
    except Exception as exc:                                      # noqa: BLE001
        row = {"label": label, "cif": key[1], "d": d_angstrom, "eps": eps,
               "rwp_pct": None, "error": f"{type(exc).__name__}: {exc}",
               "trace": traceback.format_exc()[-1200:]}
    rows.append(row)
    B._write_json("s7_broad.json", rows)
    print(json.dumps({k: row[k] for k in
                      ("label", "cif", "d", "eps", "rwp_pct", "delta")},
                     ensure_ascii=False), flush=True)


def _m45_prm_cfg(b: dict):
    """与 eval_cristobalite.stage_models_m4m5 完全同口径的精修层配置。

    差别只在 :func:`_run` 用 ``B._only(b['cfg'])``（纯前向），这里是
    Popa LB + EWIMV 织构 + ΔB_iso 都打开、``aniso_auto=True``、25 次迭代，
    即 M8 文档里「增量口径 18.06」的那套口径。
    """
    from xinrefinement.core.profile.forward import default_texture_grid
    po = B._read_json("po.json")
    best_axis: dict = {}
    for r in po:
        if (r.get("i") == 7 and r.get("delta") is not None
                and r["delta"] < -0.3 and r.get("axis")):
            ph, ax = r["phase"], tuple(int(v) for v in r["axis"])
            if ph not in best_axis or r["delta"] < best_axis[ph][1]:
                best_axis[ph] = (ax, r["delta"])
    tex = {ph: {"axis": ax, "grid": default_texture_grid()}
           for ph, (ax, _d) in best_axis.items()}
    prm0 = replace(b["prm"], texture=(tex or None), aniso=None)
    cfg0 = B._only(b["cfg"], refine_texture=True, refine_aniso=True,
                   refine_biso=True, max_iter=25, aniso_auto=True)
    return prm0, cfg0


def _run_m45(d_angstrom: float | None, eps: float, swap: Path | None,
             rows: list) -> None:
    """M4/M5 精修口径：只改方石英相的 Popa LB 起点，其它相由 auto 补。

    ``aniso_auto`` 只给「缺系数的相」补默认，故已挂宽包的方石英会保留
    我们给的起点并被 LM 精修 —— 这正是要测的「起点 / 局部极小」效应。
    """
    tag = (d_angstrom, round(eps, 6), swap.name if swap else "beta")
    if any(r.get("label") == "m45" and
           (r.get("d"), r.get("eps"), r.get("cif")) == tag and
           r.get("rwp_pct") is not None for r in rows):
        return
    try:
        pat = B._load(7, D7, D7)[0]
        b = B._load_base(7)
        prm0, cfg0 = _m45_prm_cfg(b)
        phases = list(B._refined_phases(7, D7, D7))
        idx = _crist_index(phases)
        crist = phases[idx].name
        if swap is not None:
            st = parse_cif(swap)
            st.name = crist
            phases[idx] = st

        entry = _entry(float(prm0.wavelength), d_angstrom, eps)
        if entry is not None:
            # 保留其它相的 auto 语义：只预置方石英，其余交给 _resolve_aniso
            prm0 = replace(prm0, aniso={crist: entry})
        t0 = time.time()
        res = solve(RefineInputs(pat, phases, prm0, cfg0))
        biso = {k: round(float(v), 4)
                for k, v in (res.params.b_iso or {}).items()}
        row = {"label": "m45", "d": d_angstrom, "eps": eps,
               "cif": tag[2], "rwp_pct": float(res.rwp),
               "seconds": round(time.time() - t0, 1),
               "crist_biso": biso.get(crist),
               "crist_hit_bound": bool(biso.get(crist, 0) >= 5.99),
               "weights": {p.name: (None if p.weight_pct is None
                                    else round(float(p.weight_pct), 2))
                           for p in res.phases}}
    except Exception as exc:                                      # noqa: BLE001
        row = {"label": "m45", "d": d_angstrom, "eps": eps, "cif": tag[2],
               "rwp_pct": None, "error": f"{type(exc).__name__}: {exc}",
               "trace": traceback.format_exc()[-1200:]}
    rows.append(row)
    B._write_json("s7_broad.json", rows)
    print(json.dumps({k: row.get(k) for k in
                      ("label", "cif", "d", "eps", "rwp_pct",
                       "crist_biso", "crist_hit_bound", "seconds")},
                     ensure_ascii=False), flush=True)


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "d"
    rows = B._read_json("s7_broad.json")
    if mode == "d":
        for d in D_GRID:
            _run("scan_D", d, MAUD_EPS, None, rows)
    elif mode == "strain":
        for eps in EPS_GRID:
            _run("scan_eps", MAUD_D, eps, None, rows)
    elif mode == "alpha":
        for swap in (None, LOW_S4, LOW_S6):
            for d, eps in ((MAUD_D, MAUD_EPS), (15.0, MAUD_EPS),
                           (MAUD_D, 0.0), (None, 0.0)):
                _run("alpha_x_broad", d, eps, swap, rows)
    elif mode == "m45":
        # 基准（全靠 auto）+ MAUD 宽包 + 温和宽包，各配 β / α 两相
        cases = (
            (None, 0.0, None),                 # 基线：M8 的 18.06
            (MAUD_D, MAUD_EPS, None),         # MAUD Delft 参数
            (200.0, MAUD_EPS, None),          # 纯前向扫描的最佳 D
            (200.0, 0.0, None),              # 只加尺寸宽化
            (None, 0.0, LOW_S4),             # α 相基线：M8 的 15.59
            (MAUD_D, MAUD_EPS, LOW_S4),      # α + MAUD 宽包
            (200.0, MAUD_EPS, LOW_S4),       # α + 温和宽包
        )
        for d, eps, swap in cases:
            _run_m45(d, eps, swap, rows)
    else:
        print(f"未知模式: {mode}")
        return 2
    good = [r for r in rows if r.get("rwp_pct") is not None]
    if good:
        best = min(good, key=lambda r: r["rwp_pct"])
        print(f"\n当前最佳: {json.dumps(best, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
