"""ShiJK 7 样「我们 vs MAUD」对标评测（v1.5，2026-11-07）。

为什么单独写一个脚本
--------------------
``bench_v14.py`` 只记录 Rwp 与耗时，够做回归、不够做**评测**。一份能拿去
评审的对标报告至少还要回答三件事：

1. **定量是否一致**——同一套谱、同一组相，我们与 MAUD 的 Rietveld 体积分数
   差多少（这是 XRD 定量分析的最终交付物，不是 Rwp）；
2. **模型参数是否落在同一处**——晶胞、晶粒尺寸、微应变、零点；Rwp 相近但
   参数跑偏，说明是两套不同的解，不能互相当验证；
3. **残差长什么样**——差在哪个 2θ 段、哪一相，是系统性的还是噪声。

本脚本因此做三件事：跑我们的最优配方链（口径与 ``bench_v14.py
combo_tex_aniso`` 逐项相同）→ 抽全参数 → 解析同目录 MAUD 的 ``.par`` /
``.par.lst`` 抽对应量 → 落 JSON 与逐样 obs/calc CSV 供画图。

用法::

    python tools/eval_shijk_report.py                 # 7 样全跑（约 2 h）
    python tools/eval_shijk_report.py 1,3             # 只跑指定样
    python tools/eval_shijk_report.py --maud-only     # 只解析 MAUD 侧

输出：``C:/Temp/maud_compare/shijk_report/``（临时数据，不入 Git）
  - ``report.json``        逐样全量结果（含续跑：已完成的样会跳过）
  - ``fit_<i>.csv``        逐点 2θ / obs / calc / 残差
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np                                                # noqa: E402

import bench_v14 as B                                             # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner         # noqa: E402
from xinrefinement.core.refine.solve import solve, RefineInputs   # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams      # noqa: E402

OUT = Path(r"C:/Temp/maud_compare/shijk_report")
OUT.mkdir(parents=True, exist_ok=True)
JSON_PATH = OUT / "report.json"

#: 与 ``bench_v14.stage_combo_tex_aniso`` 完全一致的开关组合
COMBO_EXTRA = {"po_probe": True, "refine_biso": True, "refine_xyz": True,
               "refine_texture": True, "refine_aniso": True, "refine_eta": True}

_NUM = r"([-+0-9.]+(?:[EeDd][-+]?\d+)?)"


# ---------------------------------------------------------------- MAUD 侧
def _strip_err(tok: str) -> float:
    """``4.6407747(9.7659075E-5)`` -> 4.6407747。"""
    return float(re.split(r"[(#]", tok.strip())[0])


def maud_par_path(d: Path) -> Path | None:
    """挑出**有内容**的 ``.par``（K25：6#.par.lst 是空文件，要用 6b#.par）。"""
    best, best_len = None, -1
    for par in sorted(d.glob("*.par")):
        lst = par.with_suffix(par.suffix + ".lst")
        n = lst.stat().st_size if lst.exists() else 0
        if n > best_len:
            best, best_len = par, n
    return best


def parse_maud(d: Path) -> dict:
    par = maud_par_path(d)
    if par is None:
        raise FileNotFoundError(f"{d.name}: 没有 .par")
    txt = par.read_text(encoding="utf-8", errors="ignore")
    lst = par.with_suffix(par.suffix + ".lst")
    ltxt = lst.read_text(encoding="utf-8", errors="ignore") if lst.exists() else ""

    out: dict = {"par": par.name, "lst": lst.name if lst.exists() else None}

    m = re.search(r"Global Rwp:\s*" + _NUM, ltxt)
    out["rwp_pct"] = float(m.group(1)) * 100.0 if m else None
    m = re.search(r"Global Rwpnb \(no background\):\s*" + _NUM, ltxt)
    out["rwp_nb_pct"] = float(m.group(1)) * 100.0 if m else None

    # ---- 相：按 _pd_phase_name 切片
    blocks = re.split(r"_pd_phase_name\s+", txt)[1:]
    phases = []
    for blk in blocks:
        name_m = re.match(r"'?([^'\n]+)'?", blk.strip())
        name = name_m.group(1).strip() if name_m else "?"
        def grab(key, _b=blk):
            mm = re.search(re.escape(key) + r"\s+" + _NUM, _b)
            return _strip_err(mm.group(1)) if mm else None
        phases.append({
            "name": name,
            "sg": (re.search(r"_symmetry_space_group_name_H-M\s+(\S+)", blk)
                   or [None, None])[1] if re.search(
                       r"_symmetry_space_group_name_H-M\s+(\S+)", blk) else None,
            "a": grab("_cell_length_a"), "b": grab("_cell_length_b"),
            "c": grab("_cell_length_c"),
            "alpha": grab("_cell_angle_alpha"),
            "beta": grab("_cell_angle_beta"),
            "gamma": grab("_cell_angle_gamma"),
            "size_A": grab("_riet_par_cryst_size"),
            "strain": grab("_riet_par_rs_microstrain"),
        })
    out["phases"] = phases

    # ---- 体积分数。两处来源都要看：
    #   .par 参数段：`Volume fraction of X  Value: 0.4253, ...`（含 not refinable 的相）
    #   .lst 参数表：`Volume fraction of X  value:0.2263 error:0.0012`
    # 只用 .lst 会漏掉"不可精修"的那一相（通常是最大相），体积分数之和永远 <1。
    vol: dict = {}
    for src in (txt, ltxt):
        # `Volume fraction of X  Value: 0.4253,` —— 出现在 .lst 的
        # "Parameter informations" 段，**且只对这相出现**（不可精修的相只有
        # 这里才有），所以必须两个文件都扫、两种大小写都试。
        for mm in re.finditer(r"Volume fraction of (.+?)\s+Value:\s*" + _NUM, src):
            vol.setdefault(mm.group(1).strip(), {"v": float(mm.group(2)),
                                                 "err": None})
    for mm in re.finditer(r"Volume fraction of (.+?)\s+value:\s*" + _NUM
                          + r" error:\s*" + _NUM, ltxt):
        k = mm.group(1).strip()
        vol.setdefault(k, {"v": float(mm.group(2)), "err": None})
        vol[k]["err"] = float(mm.group(3))
    out["vol_frac"] = vol

    # ---- 全局参数
    def g(key):
        for src in (txt, ltxt):
            mm = re.search(re.escape(key) + r"\s+(?:value:\s*)?" + _NUM, src)
            if mm:
                return _strip_err(mm.group(1))
        return None
    out["zero"] = g("_riet_par_2-theta_offset0")
    out["bg_interp"] = ("_riet_par_background_interpolated true" in txt)
    out["tex_model"] = sorted(set(re.findall(
        r"_pd_proc_ls_pref_orient_corr\s+'?([A-Za-z]+)'?", txt)))
    out["size_strain_model"] = sorted(set(re.findall(
        r"_riet_size_strain_model\s+'?([A-Za-z ]+?)'?\s*$", txt, re.M)))
    out["n_phases"] = len(phases)
    return out


# ---------------------------------------------------------------- 我们这边
def _qpa_from_result(res) -> dict:
    """把 PhaseInfo 换成体积分数 + 质量分数（两套口径都给）。"""
    rows = []
    for p in res.phases:
        rows.append({
            "name": p.name,
            "scale": float(p.scale),
            "volume_A3": float(p.volume),
            "z": (None if p.z is None else int(p.z)),
            "cell": [float(v) for v in p.cell],
            "weight_pct": (None if p.weight_pct is None
                           else float(p.weight_pct)),
        })
    # Rietveld 体积分数 v ∝ s·V²（与 MAUD 的 "Volume fraction" 同定义）
    raw = [r["scale"] * r["volume_A3"] ** 2 for r in rows]
    tot = sum(raw) or 1.0
    for r, v in zip(rows, raw):
        r["vol_pct"] = 100.0 * v / tot
    return {"phases": rows}


def _residual_bins(tt, yo, yc, sig, step=10.0) -> list[dict]:
    w = 1.0 / sig ** 2
    ss = w * (yo - yc) ** 2
    tot = float(ss.sum()) or 1.0
    lo, hi = float(tt[0]), float(tt[-1])
    bins = []
    x = np.floor(lo / step) * step
    while x < hi:
        m = (tt >= x) & (tt < x + step)
        if m.sum() >= 5:
            denom = float((w[m] * yo[m] ** 2).sum()) or 1.0
            bins.append({"lo": float(x), "hi": float(x + step),
                         "ss_pct": 100.0 * float(ss[m].sum()) / tot,
                         "rwp_pct": 100.0 * float(np.sqrt(float(ss[m].sum()) / denom))})
        x += step
    return bins


def run_one(i: int, d: Path, pdir: Path) -> dict:
    res, recs, runner, secs = B._full_recipe(i, d, pdir, dict(COMBO_EXTRA), 120.0)
    if res is None:
        raise RuntimeError("配方无结果")
    p = res.params
    tt = np.asarray(res.pattern.two_theta, float)
    yo = np.asarray(res.pattern.intensity, float)
    yc = np.asarray(res.ycalc, float)[: tt.size]
    sig = np.sqrt(np.maximum(yo, 1.0))

    row = {
        "i": i, "sample": d.name,
        "rwp_pct": float(res.rwp),
        "seconds": secs,
        "tmin": float(tt[0]), "tmax": float(tt[-1]), "n_points": int(tt.size),
        "zero": float(p.zero),
        "U": float(p.U), "V": float(p.V), "W": float(p.W),
        "eta": float(p.eta), "asym": float(p.asym),
        "b_iso": {k: round(float(v), 4) for k, v in (p.b_iso or {}).items()},
        "texture_model": ({k: {"model": v.get("model", "ewimv"),
                               "degree": v.get("degree")}
                           for k, v in (p.texture or {}).items()}),
        "aniso_phases": sorted((p.aniso or {}).keys()),
        "xyz_report": runner.xyz_report,
        "steps": [[r.key, r.status,
                   None if r.rwp_after is None else round(r.rwp_after, 3),
                   (r.message or "")[:160]] for r in recs],
        "qpa": _qpa_from_result(res),
        "refined_phases": [{"name": st.name,
                            "cell": [float(v) for v in st.cell]}
                           for st in (runner.phases or [])],
        "bins": _residual_bins(tt, yo, yc, sig),
    }
    # 逐点 CSV（画拟合图/差谱）
    csv = OUT / f"fit_{i}.csv"
    with csv.open("w", encoding="utf-8") as fh:
        fh.write("two_theta,obs,calc,resid\n")
        for a, b_, c_ in zip(tt, yo, yc):
            fh.write(f"{a:.4f},{b_:.4f},{c_:.4f},{b_ - c_:.4f}\n")
    row["csv"] = csv.name
    return row


def main(argv: list[str]) -> int:
    want: set[int] = set()
    maud_only = "--maud-only" in argv
    for a in argv[1:]:
        if re.fullmatch(r"[\d,]+", a):
            want = {int(x) for x in a.split(",") if x}

    rows = json.loads(JSON_PATH.read_text(encoding="utf-8")) \
        if JSON_PATH.exists() else []
    done = {r["i"] for r in rows if r.get("rwp_pct") is not None}

    for i, d, pdir in B.sample_dirs():
        if want and i not in want:
            continue
        m = None
        try:
            m = parse_maud(d)
            print(f"[{i}] MAUD Rwp={m['rwp_pct']:.3f}%  相数={m['n_phases']}",
                  flush=True)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[{i}] MAUD 解析失败: {exc}", flush=True)
        if maud_only:
            rows = [r for r in rows if r["i"] != i]
            rows.append({"i": i, "sample": d.name, "maud": m})
            rows.sort(key=lambda r: r["i"])
            JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
            continue
        if i in done:
            print(f"[{i}] 已完成，跳过（要重跑先删 report.json 里该行）", flush=True)
            continue
        t0 = time.time()
        try:
            row = run_one(i, d, pdir)
            row["maud"] = m
            print(f"[{i}] 我们 Rwp={row['rwp_pct']:.3f}%  "
                  f"{row['seconds']:.0f}s  总 {time.time()-t0:.0f}s", flush=True)
        except Exception as exc:                                    # noqa: BLE001
            row = {"i": i, "sample": d.name, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1500:], "maud": m}
            print(f"[{i}] 失败: {exc}", flush=True)
        rows = [r for r in rows if r["i"] != i]
        rows.append(row)
        rows.sort(key=lambda r: r["i"])
        JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
