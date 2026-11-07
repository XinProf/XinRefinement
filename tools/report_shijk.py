"""ShiJK 7 样对标评测报告的图表生成（读 eval_shijk_report.py 的 report.json）。

产出（``C:/Temp/maud_compare/shijk_report/figs/``）：
  - ``fig_rwp.png``        逐样 Rwp 三方对比柱状图（MAUD / 旧版 / 新版）
  - ``fig_qpa.png``        Rietveld 体积分数散点（MAUD vs 我们，1:1 线）
  - ``fig_cell.png``       晶胞参数相对偏差（Δd/d，ppm）
  - ``fig_fit_<i>.png``    逐样拟合图（obs / calc / 差谱）
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(r"C:/Temp/maud_compare/shijk_report")
FIGS = ROOT / "figs"
FIGS.mkdir(parents=True, exist_ok=True)
OLD = Path(r"C:/Temp/maud_compare/v14/combo_tex_aniso.pre_m10.json")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

C_MAUD, C_OLD, C_NEW = "#8c8c8c", "#4472c4", "#c0392b"


def load() -> list[dict]:
    return json.loads((ROOT / "report.json").read_text(encoding="utf-8"))


def _old_rwp() -> dict[int, float]:
    if not OLD.exists():
        return {}
    return {r["i"]: r["rwp_pct"] for r in json.loads(OLD.read_text(encoding="utf-8"))
            if r.get("rwp_pct")}


def fig_rwp(rows: list[dict]) -> None:
    rows = [r for r in rows if r.get("rwp_pct")]
    xs = np.arange(len(rows))
    maud = [r["maud"]["rwp_pct"] for r in rows]
    new = [r["rwp_pct"] for r in rows]
    old_d = _old_rwp()
    old = [old_d.get(r["i"], np.nan) for r in rows]
    w = 0.27
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    ax.bar(xs - w, maud, w, label="MAUD 2（手动）", color=C_MAUD)
    if not np.all(np.isnan(old)):
        ax.bar(xs, old, w, label="旧版（v1.4 口径）", color=C_OLD)
    ax.bar(xs + w, new, w, label="新版（v1.5 M10/M11）", color=C_NEW)
    for x, v in zip(xs, maud):
        ax.text(x - w, v + 0.15, f"{v:.2f}", ha="center", fontsize=7.5, color="#555")
    for x, v in zip(xs, new):
        ax.text(x + w, v + 0.15, f"{v:.2f}", ha="center", fontsize=7.5,
                color=C_NEW, fontweight="bold")
    ax.axhline(np.mean(maud), color=C_MAUD, ls="--", lw=0.8)
    ax.axhline(np.mean(new), color=C_NEW, ls="--", lw=0.8)
    ax.text(len(xs) - 0.45, np.mean(maud) + 0.1, f"MAUD 均值 {np.mean(maud):.2f}",
            fontsize=8, color="#555", ha="right")
    ax.text(len(xs) - 0.45, np.mean(new) - 0.45, f"新版均值 {np.mean(new):.2f}",
            fontsize=8, color=C_NEW, ha="right")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"样{r['i']}" for r in rows])
    ax.set_ylabel("Rwp (%)")
    ax.set_title("ShiJK 7 样全谱拟合 Rwp：MAUD（手动） vs XinRefinement（自动配方链）")
    ax.legend(fontsize=8.5)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_rwp.png")
    plt.close(fig)


def _match_phases(row: dict) -> list[tuple[dict, dict]]:
    """我们相 ↔ MAUD 相配对：按 (a, c) 最近邻（相名两套体系完全不同）。"""
    mp = row["maud"]["phases"]
    out = []
    for op in row["qpa"]["phases"]:
        cell = op["cell"]
        best, bd = None, 1e9
        for j, q in enumerate(mp):
            if q["a"] is None:
                continue
            da = abs(q["a"] - cell[0]) / max(cell[0], 1e-9)
            dc = (abs(q["c"] - cell[2]) / max(cell[2], 1e-9)
                  if (q["c"] and cell[2]) else 0.0)
            d = da + dc
            if d < bd:
                best, bd = q, d
        if best is not None and bd < 0.02:
            out.append((op, best))
    return out


def fig_qpa(rows: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 5.6), dpi=150)
    lo, hi = 100.0, 0.0
    for r in rows:
        if not r.get("rwp_pct") or not r.get("maud"):
            continue
        vol = r["maud"]["vol_frac"]
        for op, mp in _match_phases(r):
            x = vol.get(mp["name"], {}).get("v")
            if x is None:
                continue
            x *= 100.0
            y = op["vol_pct"]
            lo, hi = min(lo, x, y), max(hi, x, y)
            ax.scatter(x, y, s=34, alpha=0.85, edgecolor="w", linewidth=0.5)
            if max(x, y) > 8.0 or abs(x - y) > 2.0:
                ax.annotate(f"样{r['i']}", (x, y), fontsize=6.5,
                            xytext=(3, 3), textcoords="offset points",
                            color="#666")
    lim = (0, max(hi, 1) * 1.08)
    ax.plot(lim, lim, "k--", lw=0.8, label="1:1")
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("MAUD 体积分数 (%)")
    ax.set_ylabel("XinRefinement 体积分数 (%)")
    ax.set_title("Rietveld 体积分数一致性（逐相，共 "
                 f"{sum(len(_match_phases(r)) for r in rows if r.get('rwp_pct'))} 点）")
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_qpa.png")
    plt.close(fig)


def fig_cell(rows: list[dict]) -> None:
    labels, da, dc = [], [], []
    for r in rows:
        if not r.get("rwp_pct") or not r.get("maud"):
            continue
        for op, mp in _match_phases(r):
            cell = op["cell"]
            if not mp.get("a") or not cell[0]:
                continue
            labels.append(f"样{r['i']}\n{mp['name'][:9]}")
            da.append((cell[0] - mp["a"]) / mp["a"] * 1e6)
            dc.append(((cell[2] - mp["c"]) / mp["c"] * 1e6
                       if (mp.get("c") and cell[2]) else np.nan))
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(10, 4.0), dpi=150)
    ax.bar(x - 0.2, da, 0.4, label="Δa/a (ppm)", color="#4472c4")
    ax.bar(x + 0.2, dc, 0.4, label="Δc/c (ppm)", color="#ed7d31")
    ax.axhline(0, color="k", lw=0.8)
    ax.axhline(200, color="#999", ls=":", lw=0.8)
    ax.axhline(-200, color="#999", ls=":", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.5)
    ax.set_ylabel("相对偏差 (ppm)")
    ax.set_title("晶胞参数一致性：XinRefinement − MAUD（虚线 = ±200 ppm）")
    ax.legend(fontsize=8.5)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_cell.png")
    plt.close(fig)


def fig_fit(rows: list[dict]) -> None:
    for r in rows:
        if not r.get("rwp_pct") or "csv" not in r:
            continue
        csv = ROOT / r["csv"]
        if not csv.exists():
            continue
        data = np.genfromtxt(csv, delimiter=",", names=True)
        tt, yo, yc = data["two_theta"], data["obs"], data["calc"]
        fig, ax = plt.subplots(figsize=(9.5, 3.6), dpi=150)
        ax.plot(tt, yo, "k.", ms=1.2, label="观测")
        ax.plot(tt, yc, "-", color=C_NEW, lw=0.9, label="计算")
        scale = max(np.percentile(yo, 99.5), 1.0)
        ax.plot(tt, (yo - yc) - 0.06 * scale, "-", color="#3a3", lw=0.6,
                label="差谱（下移）")
        ax.axhline(-0.06 * scale, color="#3a3", lw=0.4, ls=":")
        ax.set_xlim(tt[0], tt[-1])
        ax.set_xlabel("2θ (°)"); ax.set_ylabel("强度 (counts)")
        ax.set_title(f"样 {r['i']}（{r['sample'][:18]}…）  "
                     f"Rwp {r['rwp_pct']:.2f}%  (MAUD {r['maud']['rwp_pct']:.2f}%)")
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(FIGS / f"fig_fit_{r['i']}.png")
        plt.close(fig)


def main() -> None:
    rows = load()
    fig_rwp(rows)
    fig_qpa(rows)
    fig_cell(rows)
    fig_fit(rows)
    print("figs ->", FIGS)


if __name__ == "__main__":
    main()
