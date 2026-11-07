"""逐峰宽度归因：把 Rwp 残差拆到「高斯项 / 洛伦兹项」并对照实测峰宽。

动机
----
v1.5 样 7 攻关时发现计算峰系统性偏宽 13–44%（FWHM_calc/FWHM_obs），
但「偏宽」是三种机制叠加的结果，必须分开看才能决定改哪个参数：

* **高斯项** ``fwhm_gaussian(2θ, U, V, W)`` —— 仪器 + 谱仪函数，全谱一份，
  与相无关。若各峰的偏宽比例随 2θ 平行移动，主因在这里。
* **洛伦兹项** ``fwhm_lorentz(2θ, X, Y)`` —— TCH 尺寸（∝1/cosθ）与应变
  （∝tanθ）。开 Popa LB 各向异性时 ``X/Y`` 由每峰晶向经 ``aniso_xy`` 逐峰
  取代，故这一项是**相相关 + 方向相关**的。
* **混合比 η** —— 洛伦兹比例越高，峰尾越长，双峰重叠处的「表观变宽」越明显。

判据
----
本工具对每个强峰给出

    FWHM_calc = fg ⊕ fl(逐峰)   （TCH 组合，非简单相加）
    ratio     = FWHM_calc / FWHM_obs

并把 ``fl/(fg+fl)`` 作为洛伦兹占比。经验上：

* ratio > 1.2 且洛伦兹占比 > 0.5  → 各向异性 size 在硬撑宽度，该相该方向
  的 size 张量自由度过大（或起点过大），应换应变项或收紧边界。
* ratio > 1.2 且洛伦兹占比 < 0.3  → 高斯项 U/V/W 全局过宽，属仪器项误配，
  应重跑 ``profile`` 步或检查是否存在零位/晶胞耦合。
* ratio < 0.85 且峰高比也低      → 不是宽度问题，是强度（织构/占位/B_iso）。

实测 FWHM 的取法：在峰位附近取 ±0.6° 窗口，去线性本底后按半高宽直接量，
不用任何拟合，避免把 Kα2 或邻峰卷进来（只用于**相对比较**，不作绝对精度）。

用法
----
    python tools/diag_peak_width.py --pkl C:/Temp/maud_compare/v14/diag_7_ta.pkl
    python tools/diag_peak_width.py --pkl ... --tmin 15 --tmax 32 --top 12
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xinrefinement.core.profile.forward import _peaks_with_po, aniso_xy  # noqa: E402
from xinrefinement.core.profile.size_strain import (  # noqa: E402
    fwhm_gaussian,
    fwhm_lorentz,
    tch_combine,
    tch_eta,
)
from xinrefinement.core.profile.forward import MIN_W  # noqa: E402


def _obs_fwhm(x: np.ndarray, y: np.ndarray, pos: float,
              half_win: float = 0.6,
              blockers: tuple[float, ...] = ()) -> tuple[float, float]:
    """峰位附近实测 (高度, 半高宽)，线性本底扣除，不做任何拟合。

    ``blockers`` 给出落在取窗内的**邻峰位置**；只要存在，实测半高宽就不
    可信（半高点被邻峰肩部抬高或压低），直接返回 nan 而不是给一个假装
    精确的数字。经验上重叠区量出的 FWHM 会低到 0.07°（低于仪器分辨），
    这类值以前把 ``calc/obs`` 推到 6–8 倍，纯属测量伪迹。
    """
    if blockers:
        return float("nan"), float("nan")
    m = (x >= pos - half_win) & (x <= pos + half_win)
    if m.sum() < 8:
        return float("nan"), float("nan")
    xs, ys = x[m], y[m]
    i = int(np.argmax(ys))
    ymax = float(ys[i])
    # 两端各取 8 点均值作线性本底
    k = min(8, len(ys) // 4)
    if k < 2:
        return ymax, float("nan")
    bl = np.linspace(float(ys[:k].mean()), float(ys[-k:].mean()), len(ys))
    yy = ys - bl
    ymax = float(yy[i])
    if ymax <= 0:
        return float("nan"), float("nan")
    half = ymax / 2.0
    left = right = float("nan")
    for j in range(i, 0, -1):
        if yy[j] <= half:
            t = (half - yy[j]) / (yy[j + 1] - yy[j]) if yy[j + 1] != yy[j] else 0.0
            left = float(xs[j] + t * (xs[j + 1] - xs[j]))
            break
    for j in range(i, len(ys) - 1):
        if yy[j] <= half:
            t = (half - yy[j]) / (yy[j - 1] - yy[j]) if yy[j - 1] != yy[j] else 0.0
            right = float(xs[j] - t * (xs[j] - xs[j - 1]))
            break
    if not (left == left and right == right):
        return ymax, float("nan")
    return ymax, right - left


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True, help="含 params/phases/pattern 的 pickle")
    ap.add_argument("--tmin", type=float, default=10.0)
    ap.add_argument("--tmax", type=float, default=120.0)
    ap.add_argument("--top", type=int, default=15, help="只打印计算高度最大的 N 个峰")
    ap.add_argument("--win", type=float, default=0.6, help="实测 FWHM 取窗半宽（度）")
    args = ap.parse_args(argv)

    d = pickle.load(open(args.pkl, "rb"))
    prm, phases, pat = d["params"], d["phases"], d["pattern"]
    x, y = np.asarray(pat.two_theta), np.asarray(pat.intensity)

    fg_all = []
    rows = []
    for st in phases:
        aniso = (prm.aniso or {}).get(st.name)
        bf = prm.bfactor + float((prm.b_iso or {}).get(st.name, 0.0))
        for peak in _peaks_with_po(prm, st, args.tmin, args.tmax):
            pos, height, dd = float(peak[0]), float(peak[1]), float(peak[2])
            if height <= 0:
                continue
            n = peak[3] if len(peak) > 3 else (0.0, 0.0, 1.0)
            if aniso is not None:
                xd, yd = aniso_xy(aniso, n, prm.wavelength)
            else:
                xd, yd = prm.X, prm.Y
            W = max(prm.W, MIN_W)
            fg = fwhm_gaussian(pos, prm.U, prm.V, W)
            fl = fwhm_lorentz(pos, xd, yd) if (xd or yd) else 0.0
            fw = max(tch_combine(fg, fl) if (xd or yd) else fg, MIN_W)
            eta = tch_eta(fg, fl) if (xd or yd) else prm.eta
            # B 因子对峰高的衰减（exp(-B/(2d^2)) 已在高度里，这里只做记录）
            rows.append(dict(phase=st.name, hkl=tuple(int(round(v)) for v in n),
                             pos=pos, h=height, d=dd, fg=fg, fl=fl,
                             fwhm=fw, eta=eta, bf=bf,
                             lor_frac=fl / (fg + fl) if (fg + fl) else 0.0))
            fg_all.append(fg)

    rows.sort(key=lambda r: -r["h"])
    # Kα1/Kα2 双线是**同一 hkl** 的两条线（间隔 0.08°），若不去重，每条都
    # 会被自己的 Kα2 判成邻峰污染。按 (相, hkl) 保留最高者。
    seen: set[tuple] = set()
    dedup = []
    for r in rows:
        k = (r["phase"], r["hkl"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    rows = dedup
    all_rows = rows
    rows = rows[: args.top]

    def _blockers(r) -> tuple[float, ...]:
        """取窗内是否有可比邻峰——有则该峰实测宽度不可用。

        取窗按**该峰计算 FWHM 自适应**（``4×FWHM``，钳在 0.3–1.2°）：宽包
        用宽窗、尖峰用窄窗，否则 5 相混合谱里几乎每个峰都被判污染（固定
        0.6° 窗时 12/12 全被拦掉）。
        """
        w = min(1.2, max(0.3, 4.0 * r["fwhm"]))
        out = []
        for o in all_rows:
            if o is r:
                continue
            if abs(o["pos"] - r["pos"]) <= w and o["h"] > 0.10 * r["h"]:
                out.append(o["pos"])
        return tuple(out)

    def _win(r) -> float:
        return min(1.2, max(0.3, 4.0 * r["fwhm"]))

    print(f"模型：U={prm.U:.5f} V={prm.V:.5f} W={prm.W:.5f} eta={prm.eta:.3f} "
          f"zero={prm.zero:+.5f} asym={prm.asym:+.4f}")
    print(f"aniso_mode 覆盖相数 = {len(prm.aniso or {})}；X/Y 标量 = "
          f"{prm.X:.5f}/{prm.Y:.5f}")
    print()
    hdr = (f"{'2θ':>7} {'相':<22} {'hkl':<12} {'d':>6} "
           f"{'FWHM_g':>7} {'FWHM_l':>7} {'FWHM':>6} {'η':>5} "
           f"{'obs':>6} {'calc/obs':>8} {'L占比':>6} {'B_iso':>6}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        _h, fo = _obs_fwhm(x, y, r["pos"] + prm.zero, _win(r),
                           _blockers(r))
        ratio = r["fwhm"] / fo if (fo == fo and fo > 0) else float("nan")
        short = r["phase"].split()[-1][:16]
        fo_s = "  —   " if fo != fo else f"{fo:6.4f}"
        ra_s = "  ——  " if ratio != ratio else f"{ratio:8.3f}"
        print(f"{r['pos']:7.3f} {short:<22} {str(r['hkl']):<12} {r['d']:6.3f} "
              f"{r['fg']:7.4f} {r['fl']:7.4f} {r['fwhm']:6.4f} {r['eta']:5.2f} "
              f"{fo_s} {ra_s} {r['lor_frac']:6.2f} {r['bf']:6.2f}")

    print()
    print("说明：FWHM_g 为 Caglioti 高斯项（全谱共用），FWHM_l 为 TCH 洛伦兹项"
          "（开 aniso 时逐峰由晶向决定），FWHM 为二者 TCH 组合。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
