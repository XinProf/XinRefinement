"""M0.2 命令行入口：单条谱图 Rietveld 精修，输出 JSON / TXT 报告。

用法::

    python -m xinrefinement.cli refine <pattern> <cif> [<cif2> ...] [-o report.json]

``refine`` 子命令可省略（裸参数自动补全）。退出码：0=收敛，1=未收敛，2=参数错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import DEFAULT_WAVELENGTH, ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, SolveResult, solve

_ANODES = ("Cu", "Co", "Cr", "Fe", "Mo", "Ag", "none")


def _add_refine_parser(sub) -> None:
    r = sub.add_parser("refine", help="对单条谱图做 Rietveld 精修并输出报告")
    r.add_argument("pattern", help="谱图文件（.xy/.txt/.dat/.csv/...）")
    r.add_argument("cif", nargs="+", help="CIF 结构文件（多相时有几个写几个）")
    r.add_argument("-o", "--out", default="refine_report.json", help="报告输出路径")
    r.add_argument("--format", choices=["auto", "json", "txt"], default="auto")
    r.add_argument("--tmin", type=float, default=5.0)
    r.add_argument("--tmax", type=float, default=90.0)
    r.add_argument("--anode", default="Cu", choices=_ANODES,
                   help="阳极靶（none=单色光）")
    r.add_argument("--wavelength", type=float, default=DEFAULT_WAVELENGTH)
    r.add_argument("--zero", type=float, default=0.0, help="零点初值（度）")
    r.add_argument("--n-bg", type=int, default=3, help="背景项数/节点数")
    r.add_argument("--bg-mode", choices=["cheb", "tent"], default="cheb")
    r.add_argument("--backend", choices=["lm", "scipy"], default="lm")
    r.add_argument("--max-iter", type=int, default=40)
    r.add_argument("--refine-eta", action="store_true")
    r.add_argument("--refine-asym", action="store_true")
    r.add_argument("--refine-bfactor", action="store_true")
    r.add_argument("--refine-po", action="store_true")
    r.add_argument("--refine-size", action="store_true")
    r.add_argument("--refine-strain", action="store_true")
    r.add_argument("--peak-height", action="store_true",
                   help="峰高口径（默认积分强度口径；合成 bench 数据用此项）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xinrefinement", description="XinRefinement 全谱拟合（Rietveld）命令行")
    sub = p.add_subparsers(dest="command")
    _add_refine_parser(sub)
    return p


def _build_inputs(args) -> RefineInputs:
    pat = load_pattern(args.pattern)
    phases = [parse_cif(p) for p in args.cif]
    prm = ProfileParams(
        zero=args.zero,
        wavelength=args.wavelength,
        anode=None if args.anode == "none" else args.anode,
        integrated=not args.peak_height,
    )
    cfg = RefineConfig(
        refine_zero=True,
        refine_uvw=True,
        refine_eta=args.refine_eta,
        refine_asym=args.refine_asym,
        refine_bfactor=args.refine_bfactor,
        refine_po=args.refine_po,
        refine_size=args.refine_size,
        refine_strain=args.refine_strain,
        n_bg=args.n_bg,
        bg_mode=args.bg_mode,
        max_iter=args.max_iter,
        backend=args.backend,
        tmin=args.tmin,
        tmax=args.tmax,
    )
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def _round(v, n: int = 6):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return v


def _round_list(a, n: int = 6) -> list[float]:
    return [_round(v, n) for v in np.asarray(a, dtype=float).ravel()]


def to_report(res: SolveResult, args) -> dict:
    return {
        "input": {
            "pattern": str(args.pattern),
            "cif": [str(p) for p in args.cif],
            "tmin": args.tmin,
            "tmax": args.tmax,
            "anode": args.anode,
        },
        "r_factors": {
            "rwp": _round(res.rwp),
            "rp": _round(res.rp),
            "rexp": _round(res.rexp),
            "chi2": _round(res.chi2),
            "rbragg": None if res.rbragg is None else _round(res.rbragg),
        },
        "fit": {
            "success": bool(res.success),
            "iters": int(res.iters),
            "restarted": bool(res.restarted),
        },
        "parameters": {
            "zero": _round(res.params.zero),
            "U": _round(res.params.U),
            "V": _round(res.params.V),
            "W": _round(res.params.W),
            "eta": _round(res.params.eta),
            "asym": _round(res.params.asym),
            "bfactor": _round(res.params.bfactor),
            "X": _round(res.params.X),
            "Y": _round(res.params.Y),
            "wavelength": _round(res.params.wavelength),
            "anode": res.params.anode,
        },
        "background": _round_list(res.background),
        "phases": [
            {
                "name": p.name,
                "formula": p.formula,
                "scale": _round(p.scale),
                "weight_pct": None if p.weight_pct is None else _round(p.weight_pct, 4),
                "z": p.z,
                "volume": _round(p.volume),
                "cell": [_round(v, 6) for v in p.cell],
            }
            for p in res.phases
        ],
        "history": _round_list(res.history, 4),
        "warnings": list(res.warnings),
    }


def to_text(report: dict) -> str:
    rf = report["r_factors"]
    params = report["parameters"]
    fit = report["fit"]
    lines = [
        "# XinRefinement 精修报告（M0）",
        "",
        f"- 谱图: {report['input']['pattern']}",
        f"- CIF : {', '.join(report['input']['cif'])}",
        f"- 窗口: [{report['input']['tmin']:g}, {report['input']['tmax']:g}]°"
        f"  阳极: {report['input']['anode']}",
        "",
        f"- Rwp = {rf['rwp']:.3f}%   Rp = {rf['rp']:.3f}%   "
        f"Rexp = {rf['rexp']:.3f}%   chi2 = {rf['chi2']:.3f}",
        f"- 收敛: success={fit['success']}  iters={fit['iters']}  "
        f"restarted={fit['restarted']}",
        "",
        "## 峰形参数",
        f"- zero={params['zero']:+.6f}  U={params['U']:.6f}  V={params['V']:+.6f}  "
        f"W={params['W']:.6f}  eta={params['eta']:.4f}",
        f"- asym={params['asym']:+.6f}  bfactor={params['bfactor']:.6f}  "
        f"X={params['X']:.6f}  Y={params['Y']:.6f}",
        "",
        "## 物相",
        "| 相 | scale | 质量分数% | Z | V(A^3) | 晶胞 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for p in report["phases"]:
        wt = "—" if p["weight_pct"] is None else f"{p['weight_pct']:.4f}"
        cell = ", ".join(f"{v:.4f}" for v in p["cell"])
        z = "—" if p["z"] is None else p["z"]
        lines.append(f"| {p['name']} | {p['scale']:.6f} | {wt} | "
                     f"{z} | {p['volume']:.4f} | {cell} |")
    lines += ["", "## 背景系数",
              ", ".join(f"{v:.6f}" for v in report["background"])]
    if report["warnings"]:
        lines += ["", "## 警告"] + [f"- {w}" for w in report["warnings"]]
    lines.append("")
    return "\n".join(lines)


def _run(args) -> int:
    res = solve(_build_inputs(args))
    report = to_report(res, args)
    out = Path(args.out)
    fmt = args.format
    if fmt == "auto":
        fmt = "json" if out.suffix.lower() == ".json" else "txt"
    text = (json.dumps(report, ensure_ascii=False, indent=2)
            if fmt == "json" else to_text(report))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if res.success else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] not in ("refine", "-h", "--help"):
        argv = ["refine", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "refine":
        parser.print_help()
        return 2
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
