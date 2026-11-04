"""P4.3 · GSAS-II 参考精修（外部软件交叉验证用）。

**必须用 GSAS-II 自带解释器运行**（本机 ``C:/gsas2main/python.exe``），
因为 GSASII 包只在其发行目录里：

    C:/gsas2main/python.exe tools/gsas2_reference.py \\
        --pattern "<实样.txt>" --cif xinrefinement/data/cif/NCA_80_15_05.cif \\
        --out build/crossval/gsas2_ncm811.json --tmin 10 --tmax 80

输出 JSON（晶胞 / wR / 相分数 / 步数），供 :mod:`tools.cross_validate`
与我们的结果对比。**只比结构量**（晶胞、相分数）；Rwp 因实现与口径差异
仅登记，不设通过门限。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

GSAS_DIRS = (Path(r"C:/gsas2main/GSAS-II"),)


def _ensure_importable() -> None:
    for d in GSAS_DIRS:
        if d.exists() and str(d) not in sys.path:
            sys.path.insert(0, str(d))


def _write_xye(pattern: Path, out: Path, tmin: float, tmax: float) -> Path:
    """两列 (2θ, I) -> GSAS-II 可读三列 xye（σ=√max(I,1)），并裁剪窗口。"""
    import numpy as np

    raw = np.loadtxt(pattern, comments=("#", ";", "!"), ndmin=2)
    if raw.shape[1] < 2:
        raise SystemExit(f"无法解析谱图列数：{raw.shape}")
    x, y = raw[:, 0].astype(float), raw[:, 1].astype(float)
    keep = (x >= tmin) & (x <= tmax)
    x, y = x[keep], y[keep]
    sig = np.sqrt(np.maximum(y, 1.0))
    np.savetxt(out, np.column_stack([x, y, sig]), fmt="%.6f")
    return out


def _write_instprm(path: Path, wavelength: float, ka2: float) -> Path:
    """GSAS-II instprm（Cu Kα 双线，Bragg-Brentano 平板）。

    注意键名必须是 ``Lam1`` / ``Lam2``：写成 ``Lam:1.54,1.54`` 会被读成
    字符串，后续 ``wave/(2 sinθ)`` 直接 TypeError（实测踩坑）。
    """
    path.write_text(
        "#GSAS-II instrument parameter file; do not add/delete items!\n"
        f"Type:PXC\nLam1:{wavelength:.5f}\nLam2:{ka2:.5f}\n"
        "I(L2)/I(L1):0.5\nZero:0.0\nPolariz.:0.7\nAzimuth:0.0\n"
        "U:2.0\nV:-2.0\nW:5.0\nX:0.0\nY:0.0\nZ:0.0\nSH/L:0.002\n"
        "Diff-type:Bragg-Brentano\n",
        encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GSAS-II 参考精修（P4.3）")
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--cif", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmin", type=float, default=10.0)
    ap.add_argument("--tmax", type=float, default=80.0)
    ap.add_argument("--n-bg", type=int, default=4)
    ap.add_argument("--wavelength", type=float, default=1.54051)
    ap.add_argument("--ka2", type=float, default=1.54433)
    args = ap.parse_args(argv)

    _ensure_importable()
    from GSASII import GSASIIscriptable as G2sc

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="xr_g2_"))
    xye = _write_xye(Path(args.pattern), work / "data.xye",
                     args.tmin, args.tmax)
    prm = _write_instprm(work / "cu_ka.instprm", args.wavelength, args.ka2)

    gpx = work / "g2.gpx"
    proj = G2sc.G2Project(newgpx=str(gpx))
    phases = []
    for c in args.cif:
        p = Path(c)
        phases.append(proj.add_phase(phasename=p.stem, phasefile=str(p)))
    hist = proj.add_powder_histogram(str(xye), str(prm), phases=phases)
    hist.set_refinements({"Limits": {"lowTrain": args.tmin,
                                     "highTrain": args.tmax}})
    hist.set_refinements({"Background": {"type": "chebyschev-1",
                                         "no. coeffs": args.n_bg,
                                         "refine": True}})
    hist.set_refinements({"Sample Parameters": ["Scale"]})
    proj.do_refinements([{}])
    hist.set_refinements({"Instrument Parameters":
                          ["U", "V", "W", "X", "Y", "Zero"]})
    proj.do_refinements([{}])
    for p in phases:
        p.set_refinements({"Cell": True})
    proj.do_refinements([{}])
    proj.save()

    lst = out.with_suffix(".lst")
    lst_text = ""
    # do_refinements 把 .lst 写到 gpx 同名位置（temp 目录，跨盘不能 rename）
    import shutil
    for cand in (gpx.with_suffix(".lst"), work / "g2.lst"):
        if cand.exists():
            lst_text = cand.read_text(encoding="utf-8", errors="replace")
            shutil.copyfile(cand, lst)
            break

    # 相分数（单相时为 1；多相 GSAS-II 需在 GUI 里勾选相分数精修）
    fracs = [float(m) for m in re.findall(
        r"Phase fraction\s*:\s*([0-9.]+)", lst_text)]

    payload = {
        "software": "GSAS-II",
        "pattern": str(args.pattern),
        "cifs": [str(c) for c in args.cif],
        "window": [args.tmin, args.tmax],
        "n_bg": args.n_bg,
        "wr_pct": float(hist.get_wR()),
        "phases": [
            {"name": p.name, "cell": [float(v) for v in
                                      (p.get_cell()["length_a"],
                                       p.get_cell()["length_b"],
                                       p.get_cell()["length_c"],
                                       p.get_cell()["angle_alpha"],
                                       p.get_cell()["angle_beta"],
                                       p.get_cell()["angle_gamma"])]}
            for p in phases
        ],
        "phase_fractions": fracs[: len(phases)],
        "lst": str(lst) if lst.exists() else None,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
