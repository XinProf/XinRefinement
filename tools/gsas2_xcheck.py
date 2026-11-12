"""用 GSAS-II 对 IUCr CPD 样品做**完全独立**的 Rietveld 精修，取一份第三方 Rwp。

为什么要这个
------------
``tools/eval_iucr_qpa.py`` 给的是**我们自己引擎**的 Rwp 与定量误差。判断
「我们 12.0% 到底是好是坏」需要一把外部尺子：MAUD 与 GSAS-II 是两个
被广泛接受的独立实现。MAUD 已在 ShiJK 数据集上比过，但在 IUCr CPD 上
没有 MAUD 结果，而本机有 GSAS-II（``C:\\gsas2main``，5.8.2），可以直接
拿它当尺子。

口径对齐（关键，否则比较无意义）
--------------------------------
* **权重**：``.gss`` 的 ``BANK`` 行给每点计数 ``n``，GSAS-II 取
  ``σ² = y/n``（``n ≡ 1`` 时即 ``σ² = y``）；我们 ``weight_mode="sqrt"``
  同样是 ``σ² = y``。**一致**。
* **背景**：GSAS-II 的 ``wR`` 是含背景的加权 R，涵盖整个 ``Limits``
  区间；我们改成含背景 Rwp 后同口径。**一致**。
* **窗口**：默认 5–120°，与 ``eval_iucr_qpa.py`` 的 CPD 窗口一致。
* **峰形**：GSAS-II PXCR 用 ``GU/GV/GW``（Caglioti）+ ``GP``（Lorentz 项，
  即 ``eta`` 的等价物）+ ``X/Y``（低角不对称，对应 ``tanθ`` 项）。

所以两边比的是**同一份数据、同一权重、同一窗口**，差别只剩模型与优化器。

用法
----
    C:\\gsas2main\\python.exe tools/gsas2_xcheck.py --sample 1g
    C:\\gsas2main\\python.exe tools/gsas2_xcheck.py --sample 1a --max 120
    C:\\gsas2main\\python.exe tools/gsas2_xcheck.py --gss <path> --cif a.cif --cif b.cif

结果写 ``C:/Temp/iucr/gsas2_xcheck.json``。
"""

from __future__ import annotations

import argparse
import json
import shutil
import os
import sys
import tempfile
from pathlib import Path

GSAS2 = Path(r"C:\gsas2main\GSAS-II")
GSAS_DIR = Path(r"D:\Project\XRD\XRData\IUCr\gsas")
ROOT = Path(os.environ.get("XR_IUCr_ROOT", r"d:\test_XRD\IUCr_Rietveld"))
OUT = Path(r"C:/Temp/iucr")

#: 与 tools/eval_iucr_qpa.py 保持**同一套**结构文件，否则不是同一实验。
CIF = {
    "Corundum": (Path(os.environ.get("XR_BENCH_ROOT",
                    r"d:\test_XRD\ShiJK-Refinement"))
                 / "ShiJiKong3#1##20260126-130900_100"
                 / "4Entry_96-900-9673.cif"),
    "Zincite": ROOT / "Entry_96-230-0113-ZnO.cif",
    "Fluorite": ROOT / "Entry_96-230-0450-CaF2.cif",
}

#: Sample 1 全系列都是刚玉 + ZnO + 萤石三相等质量混样，只是配比不同。
SAMPLE_PHASES = {"1a": ("Corundum", "Zincite", "Fluorite"),
                 "1b": ("Corundum", "Zincite", "Fluorite"),
                 "1c": ("Corundum", "Zincite", "Fluorite"),
                 "1d": ("Corundum", "Zincite", "Fluorite"),
                 "1e": ("Corundum", "Zincite", "Fluorite"),
                 "1f": ("Corundum", "Zincite", "Fluorite"),
                 "1g": ("Corundum", "Zincite", "Fluorite"),
                 "1h": ("Corundum", "Zincite", "Fluorite")}

#: Cu Kα1/Kα2，与 IUCr CPD 的采集条件一致（INST_XRY.PRM 同值）。
INST = """            123456789012345678901234567890123456789012345678901234567890
INS   BANK      1
INS   HTYPE   PXCR
INS  1 IRAD     3
INS  1 ICONS  1.540500  1.544300       0.0         0       0.7    0       0.5
INS  1I HEAD  IUCr CPD round-robin, Cu Ka
INS  1I ITYP    0    0.0000  180.0000         1
INS  1PRCF1     3    8      0.01
INS  1PRCF11   2.000000E+00  -2.000000E+00   5.000000E+00   0.100000E+00
INS  1PRCF12   0.000000E+00   0.000000E+00   0.150000E-01   0.150000E-01
"""


def _setup_path() -> None:
    if str(GSAS2) not in sys.path:
        sys.path.insert(0, str(GSAS2))


def calibrate_instrument(calib: Path, cif: Path, hi: float, cycles: int,
                         workdir: Path, nbg: int = 24) -> dict:
    """用纯相标样标定仪器峰形，返回 {参数名: 值}。

    这是实验室标准流程：U/V/W/X/Y/Zero 是**仪器**属性，应从标样来，
    不该在多相样品上和 scale/织构搅在一起精修——那正是脚本化分阶段
    精修卡坏极小的根源（W 从 5 被拉到 21，X/Y 跟着乱）。
    """
    _setup_path()
    from GSASII import GSASIIscriptable as G2sc
    inst = workdir / "IUCr_CuKa.PRM"
    inst.write_text(INST, encoding="latin-1")
    gpx = G2sc.G2Project(newgpx=str(workdir / "calib.gpx"))
    h = gpx.add_powder_histogram(str(calib), str(inst), fmthint="GSAS powder")
    gpx.add_phase(str(cif), phasename="STD", histograms=[h])
    gpx.set_Controls("cycles", cycles)
    h.set_refinements({"Limits": [5.0, hi]})
    h.set_refinements({"Background": {"no. coeffs": nbg, "refine": True}})
    gpx.refine(makeBack=True)
    h.set_refinements({"Sample Parameters": ["Shift"]})
    for p in gpx.phases():
        p.set_refinements({"Cell": True})
    gpx.refine(makeBack=True)
    h.set_refinements({"Instrument Parameters": ["U", "V", "W", "X", "Y", "Zero"]})
    gpx.refine(makeBack=True)
    ip = h.data["Instrument Parameters"][0]
    out = {k: float(ip[k][1]) for k in ("U", "V", "W", "X", "Y", "Zero") if k in ip}
    print(f"  [标样 {calib.name}] wR={h.residuals['wR']:.3f}%  "
          + " ".join(f"{k}={v:.4g}" for k, v in out.items()))
    return out


def build(sample: str, gss: Path, cifs: list[Path], hi: float, cycles: int,
          stages: bool, workdir: Path, nbg: int = 24, sh: int = 0,
          sh_phases: list[str] | None = None, calib: dict | None = None):
    """建工程并分阶段精修；返回 (hist, gpx, log)。"""
    _setup_path()
    from GSASII import GSASIIscriptable as G2sc  # noqa: E402

    inst = workdir / "IUCr_CuKa.PRM"
    inst.write_text(INST, encoding="latin-1")
    gpx = G2sc.G2Project(newgpx=str(workdir / f"{sample}.gpx"))
    h = gpx.add_powder_histogram(str(gss), str(inst), fmthint="GSAS powder")
    phases = [gpx.add_phase(str(c), phasename=c.stem, histograms=[h]) for c in cifs]
    if calib:
        ip = h.data["Instrument Parameters"][0]
        for k, v in calib.items():
            if k in ip:
                ip[k][1] = v

    log: list[dict] = []

    def run(tag: str) -> float:
        gpx.refine(makeBack=True)
        r = h.residuals
        log.append({"stage": tag, "wR": r["wR"], "chi2": r.get("chi2")})
        print(f"  [{tag:28s}] wR={r['wR']:7.3f}%  chi²={r.get('chi2', float('nan')):.4f}")
        return r["wR"]

    gpx.set_Controls("cycles", cycles)
    h.set_refinements({"Limits": [5.0, hi]})

    if not stages:
        for p in phases:
            p.set_refinements({"Cell": True})
        h.set_refinements({"Background": {"no. coeffs": nbg, "refine": True},
                           "Instrument Parameters": ["U", "V", "W", "X", "Y"]})
        run("all-at-once")
        return h, gpx, log

    print(f"  数据 {gss.name} / {len(phases)} 相：{[p.name for p in phases]}")
    run("初始（仅 scale）")
    # 1) 背景：GSAS-II 的 Chebyshev，6 项——比我们 tent 节点少得多，
    #    但这是它的默认口径，不额外调，避免"替它调参"。
    h.set_refinements({"Background": {"no. coeffs": nbg, "refine": True}})
    run(f"+ 背景 Chebyshev {nbg} 项")
    # 2) 晶胞：三相都放
    for p in phases:
        p.set_refinements({"Cell": True})
    run("+ 晶胞")
    # 2.5) 样品位移：IUCr CPD 这类压片样几乎必有位移，GSAS-II 默认 Shift=0
    #      且不精修，不放开就会把整谱峰位拉偏 ~0.05°，三相比对全乱。
    h.set_refinements({"Sample Parameters": ["Shift"]})
    run("+ 样品位移 Shift")
    # 3) 峰宽与零位：GU/GV/GW + X/Y 不对称 + Zero
    if calib:
        run("+ 仪器峰形（已由标样冻结）")
    else:
        h.set_refinements({"Instrument Parameters":
                           ["U", "V", "W", "X", "Y", "Zero", "SH/L"]})
        run("+ U/V/W/X/Y/Zero/SH-L")
    # 4) 微结构：逐相各向同性 size + mustrain（GSAS-II 里等价于我们的
    #    "逐相 Lorentz 展宽"，是它默认做法）
    for p in phases:
        p.set_HAP_refinements({"Size": {"refine": True},
                               "Mustrain": {"type": "isotropic", "refine": True}}, [h])
    run("+ 逐相 size/mustrain")
    if sh:
        # 球谐织构（与 MAUD 的展开阶一致）：March-Dollase 单轴修不了的
        # 取向依赖强度（如 ZnO (002) vs (101) 相对强弱）只有 SH 能表达。
        # 只对指定相放开（默认全部）：GSAS-II 的 SH 系数**无界**，给本来
        # 无织构的相放开会让 scale 被压低后用负强度硬补（实测 CaF2 (311)
        # calc = -15），卡死局部极小。
        names = set(sh_phases) if sh_phases else None
        done: list[str] = []
        for p in phases:
            if names is not None and p.name not in names:
                continue
            p.HAPvalue("PO", sh, [h])
            p.set_HAP_refinements({"Pref.Ori.": True}, [h])
            done.append(p.name)
        run(f"+ 球谐织构 SH order={sh} [{'+'.join(done)}]")
    return h, gpx, log


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", default="1g", help="CPD 样名（1a…1h）")
    ap.add_argument("--gss", type=Path, help="直接给 .gss，覆盖 --sample")
    ap.add_argument("--cif", action="append", type=Path, help="结构文件，可重复")
    ap.add_argument("--max", dest="hi", type=float, default=120.0, help="2θ 上限")
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--calib", type=Path,
                    help="仪器峰形标样 .gss（纯相），先标定 U/V/W/X/Y/Zero 再冻结")
    ap.add_argument("--calib-cif", type=Path, help="标样的结构文件")
    ap.add_argument("--sh-phase", action="append", default=None,
                    help="只对指定相放开 SH（按 CIF 文件名匹配，可重复）")
    ap.add_argument("--sh", type=int, default=0,
                    help="球谐织构展开阶（0=关；建议 8，与 MAUD 一致）")
    ap.add_argument("--bg", type=int, default=24,
                    help="背景 Chebyshev 项数（默认 24，与我们 19 节点 tent 同量级灵活度）")
    ap.add_argument("--no-stages", action="store_true", help="一次全放（不分布）")
    ap.add_argument("--keep", action="store_true", help="保留 .gpx 便于 GUI 复查")
    ap.add_argument("--dump", type=Path, help="把 x/yobs/ycalc/bkg 写成 csv 便于画差谱")
    a = ap.parse_args(argv[1:])

    gss = a.gss or (GSAS_DIR / f"cpd-{a.sample.lower()}.gss")
    if not gss.exists():
        raise SystemExit(f"缺数据文件 {gss}")
    if a.cif:
        cifs = list(a.cif)
    else:
        names = SAMPLE_PHASES.get(a.sample.lower())
        if not names:
            raise SystemExit(f"未登记 {a.sample} 的物相，用 --cif 指定")
        cifs = [CIF[n] for n in names]
    for c in cifs:
        if not c.exists():
            raise SystemExit(f"缺结构文件 {c}")

    workdir = Path(tempfile.mkdtemp(prefix="g2x_"))
    try:
        print(f"GSAS-II 独立精修 {gss.name}  窗口 5–{a.hi:g}°  cycles={a.cycles}")
        calib = None
        if a.calib:
            if not a.calib.exists() or not a.calib_cif.exists():
                raise SystemExit("标样 .gss/.cif 不存在")
            calib = calibrate_instrument(a.calib, a.calib_cif, a.hi,
                                         a.cycles, workdir, a.bg)
        h, gpx, log = build(a.sample.lower(), gss, cifs, a.hi, a.cycles,
                            not a.no_stages, workdir, a.bg, a.sh, a.sh_phase,
                            calib)
        r = h.residuals
        if a.dump:
            import numpy as _np
            cols = [_np.ma.getdata(h.getdata(k)) for k in
                    ("x", "yobs", "ycalc", "background")]
            _np.savetxt(a.dump, _np.column_stack([c[:len(cols[0])] for c in cols]),
                        delimiter=",", header="x,yobs,ycalc,bkg", comments="")
            print(f"  fit 导出 → {a.dump}")
        rec = {"sample": a.sample.lower(), "gss": str(gss),
               "cif": [str(c) for c in cifs], "window": [5.0, a.hi],
               "cycles": a.cycles, "nbg": a.bg, "sh": a.sh, "wR": r["wR"], "chi2": r.get("chi2"),
               "nobs": r.get("Nobs"), "stages": log,
               "gpx": str(workdir / f"{a.sample.lower()}.gpx")}
        OUT.mkdir(parents=True, exist_ok=True)
        dst = OUT / "gsas2_xcheck.json"
        old = json.loads(dst.read_text()) if dst.exists() else []
        old = [o for o in old if o.get("sample") != rec["sample"]]
        old.append(rec)
        dst.write_text(json.dumps(old, ensure_ascii=False, indent=1))
        print(f"\n最终 wR = {rec['wR']:.3f}%   → {dst}")
        if a.keep:
            print(f"工程保留在 {rec['gpx']}")
        return 0
    finally:
        if not a.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
