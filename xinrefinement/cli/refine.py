"""M0.2 命令行入口：单条谱图 Rietveld 精修，输出 JSON / TXT 报告。

用法::

    python -m xinrefinement.cli refine <pattern> <cif> [<cif2> ...] [-o report.json]

``refine`` 子命令可省略（裸参数自动补全）。退出码：0=收敛，1=未收敛，2=参数错误。
"""
from __future__ import annotations

import argparse
import json
import math
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
    r.add_argument("--bg-mode", choices=["cheb", "tent", "interp", "manual"],
                   default="cheb",
                   help="interp=v1.2.0 自动提取固定插值背景（MAUD 语义，"
                        "默认 10 次迭代）；manual 需配 --bg-points")
    r.add_argument("--bg-points", default="", metavar="2θ:强度,...",
                   help="manual 背景锚点，如 --bg-points 15:320,60:180")
    r.add_argument("--weight-mode", choices=["sqrt", "file", "unit", "1/y"],
                   default="sqrt",
                   help="定权模式（v1.2.0）：sqrt=计数统计（默认），"
                        "file=谱图自带 σ，unit=常数权，1/y=σ∝y")
    r.add_argument("--backend", choices=["lm", "scipy"], default="lm")
    r.add_argument("--max-iter", type=int, default=40)
    r.add_argument("--microabs", action="append", default=[], metavar="相名=μr",
                   help="Brindley 微吸收校正（v1.2.0，可多次）：如 "
                        "--microabs Goethite=1.5；μ·r=吸收系数×晶粒半径")
    r.add_argument("--refine-eta", action="store_true")
    r.add_argument("--refine-asym", action="store_true")
    r.add_argument("--refine-bfactor", action="store_true")
    r.add_argument("--refine-po", action="store_true")
    r.add_argument("--refine-size", action="store_true")
    r.add_argument("--refine-strain", action="store_true")
    r.add_argument("--peak-height", action="store_true",
                   help="峰高口径（默认积分强度口径；合成 bench 数据用此项）")
    r.add_argument("--recipe", action="store_true",
                   help="按标准导航配方分步精修（P3.3 RecipeRunner），"
                        "输出每步 Rwp；省略则单次整体精修")
    r.add_argument("--report", metavar="DIR", default=None,
                   help="导出 HTML+PNG+JSON 报告目录（P4.1）")
    r.add_argument("--quant", action="store_true",
                   help="在报告中显著输出物相质量分数表（WPF 定量）")
    r.add_argument("--esd", action="store_true",
                   help="计算并输出参数 e.s.d. 与相关系数（P1.5 Schur 补）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xinrefinement", description="XinRefinement 全谱拟合（Rietveld）命令行")
    sub = p.add_subparsers(dest="command")
    _add_refine_parser(sub)
    return p


def _parse_microabs(items: list[str]) -> dict[str, float]:
    """'相名=μr' 列表 -> {相名: μ·r}（坏项直接报错，不静默丢弃）。"""
    out: dict[str, float] = {}
    for item in items:
        name, _, val = item.partition("=")
        name, val = name.strip(), val.strip()
        if not name or not val:
            raise SystemExit(f"--microabs 格式应为 相名=μr，收到: {item!r}")
        out[name] = float(val)
    return out


def _parse_bg_points(spec: str) -> tuple:
    """'15:320,60:180' -> ((15.0, 320.0), (60.0, 180.0))。"""
    pts = []
    for item in filter(None, spec.split(",")):
        x, _, y = item.partition(":")
        pts.append((float(x), float(y)))
    if len(pts) == 1:
        raise SystemExit("--bg-points 至少需要 2 个点")
    return tuple(pts)


def _build_inputs(args) -> RefineInputs:
    pat = load_pattern(args.pattern)
    phases = [parse_cif(p) for p in args.cif]
    prm = ProfileParams(
        zero=args.zero,
        wavelength=args.wavelength,
        anode=None if args.anode == "none" else args.anode,
        integrated=not args.peak_height,
        microabs=(_parse_microabs(args.microabs) or None),
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
        bg_points=_parse_bg_points(args.bg_points),
        weight_mode=args.weight_mode,
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


def _esd_val(v: float, n: int = 6):
    """e.s.d. 值序列化：TCH 边界参数为 NaN -> None（JSON null）。"""
    v = float(v)
    return _round(v, n) if math.isfinite(v) else None


def _esd_section(esd) -> list[str]:
    """e.s.d. 表格（文本 / HTML 共用的 markdown 片段）。"""
    rows = ["", "## 参数 e.s.d.", "| 参数 | 值 | e.s.d. |",
            "|---|---:|---:|"]
    for lab, v, e in zip(esd.labels, esd.esd, esd.esd):
        ev = "—（TCH 边界，无定义）" if not math.isfinite(e) else f"±{e:.3g}"
        rows.append(f"| {lab} | {v:.6g} | {ev} |")
    if esd.weight_esd_pct is not None:
        rows += ["", "### 物相含量 e.s.d.（百分点）"]
        rows += [f"- ±{w:.3g}" for w in esd.weight_esd_pct]
    rows.append(f"- s² = {esd.variance_factor:.4g}  "
                f"Schur 一致性 = {esd.schur_consistency:.2e}")
    return rows


def _run(args) -> int:
    from xinrefinement.core.refine.recipe import RecipeRunner

    inputs = _build_inputs(args)
    recipe_rows: list[tuple[str, str, float | None, float | None]] = []
    if args.recipe:
        runner = RecipeRunner()
        res = None
        for step in runner.state.steps:
            res, rec = runner.run_step(step, inputs, res)
            recipe_rows.append((rec.key, rec.status, rec.rwp_before,
                                rec.rwp_after))
            if rec.status == "failed" or res is None:
                # StepRecord 的字段是 message（不是 note）：此前这里写 rec.note，
                # 只在**真的失败**时才触发 AttributeError，正常路径永远走不到。
                print(f"步骤 {rec.key} 失败：{rec.message}", file=sys.stderr)
                return 1
        res = res  # noqa: PLW0127 — 最后一步的结果
    else:
        res = solve(inputs)

    esd = None
    if args.esd:
        from xinrefinement.core.refine.esd import estimate_esd
        esd = estimate_esd(inputs.phases, res)

    report = to_report(res, args)
    if recipe_rows:
        report["recipe"] = [
            {"step": k, "status": s,
             "rwp_before": None if b is None else _round(b, 4),
             "rwp_after": None if a is None else _round(a, 4)}
            for k, s, b, a in recipe_rows]
    if esd is not None:
        report["esd"] = {
            "labels": list(esd.labels),
            "esd": [_esd_val(v) for v in esd.esd],
            "scale_esd": [_esd_val(v, 8) for v in esd.scale_esd],
            "weight_esd_pct": (None if esd.weight_esd_pct is None
                               else [_esd_val(v, 4)
                                     for v in esd.weight_esd_pct]),
            "variance_factor": _round(esd.variance_factor),
            "schur_consistency": _round(esd.schur_consistency, 8),
        }

    out = Path(args.out)
    fmt = args.format
    if fmt == "auto":
        fmt = "json" if out.suffix.lower() == ".json" else "txt"
    text = (json.dumps(report, ensure_ascii=False, indent=2)
            if fmt == "json" else to_text(report))
    if fmt == "txt" and esd is not None:
        text += "\n".join(_esd_section(esd))
    if args.quant:
        print()
        print("## 物相质量分数（WPF）")
        for p in report["phases"]:
            wt = "—" if p["weight_pct"] is None else f"{p['weight_pct']:.3f}%"
            print(f"  {p['name']:<24s} {wt}")
        if esd is not None and esd.weight_esd_pct is not None:
            for p, w in zip(report["phases"], esd.weight_esd_pct):
                print(f"    ± {w:.3g}")
    out.write_text(text, encoding="utf-8")
    print(text)

    if args.report:
        from xinrefinement.core.report import export_report
        paths = export_report(res, args.report, esd=esd)
        print()
        print("报告已导出：")
        for kind, p in paths.items():
            print(f"  {kind}: {p}")
    return 0 if res.success else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-V", "--version"):
        from xinrefinement import __version__
        print(f"XinRefinement {__version__}")
        return 0
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
