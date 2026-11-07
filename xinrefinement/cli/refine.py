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
    r.add_argument("--weight-mode",
                   choices=["sqrt", "file", "unit", "1/y", "theoretical"],
                   default="sqrt",
                   help="定权模式（v1.2.0/v1.3）：sqrt=计数统计（默认），"
                        "file=谱图自带 σ，unit=常数权，1/y=σ∝y，"
                        "theoretical=σ 取计算值（MAUD theoreticalWeights，抗弱峰噪声）")
    r.add_argument("--backend", choices=["lm", "trf", "dogbox", "scipy"],
                   default="lm",
                   help="优化器（v1.3 插拔）：lm=自研（默认），trf=scipy 鲁棒，"
                        "dogbox=强边界，scipy=trf 的别名")
    r.add_argument("--max-iter", type=int, default=40)
    r.add_argument("--microabs", action="append", default=[], metavar="相名=μr",
                   help="Brindley 微吸收校正（v1.2.0，可多次）：如 "
                        "--microabs Goethite=1.5；μ·r=吸收系数×晶粒半径")
    r.add_argument("--grain-size", action="append", default=[],
                   metavar="相名=r_μm",
                   help="按相化学成分自动算 μ·r（v1.3，可多次）：如 "
                        "--grain-size Goethite=3.0（球半径 μm）；"
                        "与 --microabs 同名时后者优先")
    r.add_argument("--texture", action="append", default=[],
                   metavar="相名=h0,k0,l0",
                   help="织构精修（可多次）：如 --texture anatase=0,0,1；"
                        "BB 几何下每反射一个 T(χ) 因子。模型由 "
                        "--texture-model 选择（EWIMV 19 点网格 / 球谐展开）")
    r.add_argument("--texture-model", choices=("ewimv", "harmonic"),
                   default="ewimv",
                   help="v1.5 M3 织构模型：ewimv=19 点离散 ODF（v1.3 默认）；"
                        "harmonic=球谐（Legendre）展开，MAUD Harmonic 同族，"
                        "自由度 2–4 维、基正交无需光滑罚")
    r.add_argument("--texture-degree", type=int, default=4, metavar="N",
                   help="球谐展开阶数（偶数，2/4/6/8；默认 4）；阶越高越易过拟合")
    r.add_argument("--texture-lambda", type=float, default=1.0,
                   metavar="λ",
                   help="织构网格二阶差分光滑罚权重（默认 1.0，0=关闭正则化）")
    r.add_argument("--aniso", action="append", default=[],
                   metavar="相名[=size|strain|both]",
                   help="Popa LB 各向异性尺寸/应变（v1.3，可多次）：如 "
                        "--aniso anatase=size；默认 mode=size（6 参），"
                        "both=12 参（可能不可辨识）")
    r.add_argument("--aniso-auto", action="store_true",
                   help="v1.5 M4：micro 步自动为每相启用 Popa LB 各向异性"
                        "展宽（各向同性起点，6 参/相）；方向数不足的相自动"
                        "跳过。等价于逐相 --aniso，但无需手写相名")
    r.add_argument("--refine-eta", action="store_true")
    r.add_argument("--refine-asym", action="store_true")
    r.add_argument("--refine-bfactor", action="store_true")
    r.add_argument("--refine-biso", action="store_true",
                   help="v1.4 #18：逐相精修各向同性温度因子 ΔB_iso (Å²)，"
                        "压回 COD CIF B=0 导致的高角强度偏高；"
                        "配 --recipe 时由 B 步执行")
    r.add_argument("--refine-xyz", action="store_true",
                   help="v1.4 #17：配方 xyz 步按 Wyckoff 位约束精修原子坐标"
                        "（需 --recipe；无 CIF 源路径的相自动跳过）")
    r.add_argument("--xyz-max-params", type=int, default=40, metavar="N",
                   help="xyz 步最多放开的自由坐标系数（默认 40，超出判失败）")
    r.add_argument("--xyz-phase-select", choices=("off", "largest", "small"),
                   default="largest",
                   help="自由坐标超预算时按相降级：largest=保留自由坐标最多的相"
                        "（默认，样 7 实测增量 −1.87 pt）；small=升序对照；"
                        "off=保持 v1.4 整步判失败。仅超预算时生效，"
                        "不超限的路径逐位不变")
    r.add_argument("--refine-po", action="store_true")
    r.add_argument("--po-probe", action="store_true",
                   help="v1.4 #19：配方 micro 步自动逐相试探择优取向惯习面"
                        "（需 --recipe；按 Rwp 增益选轴，默认关）")
    r.add_argument("--po-probe-min-gain", type=float, default=0.3,
                   metavar="PT", help="PO 试探接受阈值（Rwp 百分点，默认 0.3）")
    r.add_argument("--po-probe-max-phases", type=int, default=2,
                   metavar="N", help="PO 试探最多纳入相数（默认 2）")
    r.add_argument("--po-probe-max-iter", type=int, default=12,
                   metavar="N", help="每个候选轴的短精修迭代上限（默认 12）")
    r.add_argument("--refine-size", action="store_true")
    r.add_argument("--refine-strain", action="store_true")
    r.add_argument("--peak-height", action="store_true",
                   help="峰高口径（默认积分强度口径；合成 bench 数据用此项）")
    r.add_argument("--lm-lambda", type=float, default=1e-3, metavar="L",
                   help="v1.5 M7：LM 初始阻尼 λ（默认 1e-3，与 v1.0 逐位一致）。"
                        "MAUD Marquardt LS 取 0.01——越大单步越保守，"
                        "只在对照实验时改它")
    r.add_argument("--lm-step", type=float, default=1e-4, metavar="H",
                   help="v1.5 M7：数值雅可比相对步长基值（默认 1e-4，与 MAUD 一致；"
                        "改它属于实验行为）")
    r.add_argument("--recipe", action="store_true",
                   help="按标准导航配方分步精修（P3.3 RecipeRunner），"
                        "输出每步 Rwp；省略则单次整体精修")
    r.add_argument("--time-budget-min", type=float, default=0.0, metavar="MIN",
                   help="v1.5 M9b：配方连跑全链墙钟预算（分钟，默认 0 = 不限）。"
                        "超预算时 xyz/micro 慢步按实测单次评估耗时自适应降迭代，"
                        "剩余预算不足的可选步跳过（GUI 出厂默认 45）")
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


def _parse_aniso(items: list[str]):
    """'相名[=mode]' 列表 -> ({相名: 各向同性起点系数}, mode)。"""
    from xinrefinement.core.profile.forward import aniso_default

    out: dict[str, dict] = {}
    mode = "size"
    for item in items:
        name, _, spec = item.partition("=")
        name, spec = name.strip(), spec.strip()
        if not name:
            raise SystemExit(f"--aniso 格式应为 相名[=size|strain|both]，收到: {item!r}")
        if spec:
            if spec not in ("size", "strain", "both"):
                raise SystemExit(f"--aniso 模式只能是 size / strain / both，收到: {spec!r}")
            mode = spec
        out[name] = aniso_default(1.5406)
    return out, mode


def _parse_texture(items: list[str], model: str = "ewimv",
                   degree: int = 4):
    """'相名=h0,k0,l0' 列表 -> ({相名: 织构配置}, 是否启用)。

    v1.5 M3：``model`` 选 ``"ewimv"``（v1.3 的 19 点离散网格）或
    ``"harmonic"``（球谐/Legendre 展开，阶数由 ``degree`` 给，偶数）。两者互斥，
    同一相不允许同时带 ``grid`` 与 ``coeffs``——这里按模型只写一种初值。
    """
    from xinrefinement.core.profile.forward import (
        default_texture_coeffs, default_texture_grid, texture_degrees)

    mdl = str(model or "ewimv").strip().lower()
    if mdl not in ("ewimv", "harmonic"):
        raise SystemExit(f"--texture-model 只能是 ewimv / harmonic，收到: {model!r}")
    seed = ({"model": "harmonic", "degree": int(degree),
             "coeffs": default_texture_coeffs(int(degree))}
            if mdl == "harmonic" else {"grid": default_texture_grid()})
    if mdl == "harmonic":
        texture_degrees(int(degree))     # 阶数非法时在这里就报错

    out: dict[str, dict] = {}
    for item in items:
        name, _, spec = item.partition("=")
        name = name.strip()
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        if not name or len(parts) < 3:
            raise SystemExit(
                f"--texture 格式应为 相名=h0,k0,l0，收到: {item!r}")
        try:
            axis = tuple(int(round(float(p))) for p in parts[:3])
        except ValueError:
            raise SystemExit(f"--texture 指数必须是整数，收到: {item!r}")
        if axis == (0, 0, 0):
            raise SystemExit(f"--texture 织构轴不能是 0,0,0，收到: {item!r}")
        out[name] = {"axis": axis, **seed}
    return out


def _parse_grain_size(items: list[str]) -> dict[str, float]:
    """'相名=r_μm' 列表 -> {相名: r(μm)}（坏项直接报错）。"""
    out: dict[str, float] = {}
    for item in items:
        name, _, val = item.partition("=")
        name, val = name.strip(), val.strip()
        if not name or not val:
            raise SystemExit(f"--grain-size 格式应为 相名=r_μm，收到: {item!r}")
        v = float(val)
        if v <= 0:
            raise SystemExit(f"--grain-size 晶粒半径必须为正: {item!r}")
        out[name] = v
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
    # v1.3: μ·r 来源优先级 —— 手工 --microabs 覆盖按成分自动计算的 --grain-size
    microabs: dict[str, float] = {}
    if args.grain_size:
        from xinrefinement.core.absorption import calc_microabs
        anode = None if args.anode == "none" else args.anode
        microabs.update(calc_microabs(phases, _parse_grain_size(args.grain_size),
                                      anode=anode or "Cu"))
    microabs.update(_parse_microabs(args.microabs))
    texture = _parse_texture(args.texture, args.texture_model,
                             args.texture_degree)
    aniso, aniso_mode = _parse_aniso(args.aniso)
    prm = ProfileParams(
        zero=args.zero,
        wavelength=args.wavelength,
        anode=None if args.anode == "none" else args.anode,
        integrated=not args.peak_height,
        microabs=(microabs or None),
        texture=(texture or None),
        aniso=(aniso or None),
    )
    cfg = RefineConfig(
        refine_zero=True,
        refine_uvw=True,
        refine_eta=args.refine_eta,
        refine_asym=args.refine_asym,
        refine_bfactor=args.refine_bfactor,
        refine_biso=args.refine_biso,
        refine_xyz=args.refine_xyz,
        xyz_max_params=args.xyz_max_params,
        xyz_phase_select=args.xyz_phase_select,
        refine_po=args.refine_po,
        po_probe=args.po_probe,
        po_probe_min_gain=args.po_probe_min_gain,
        po_probe_max_phases=args.po_probe_max_phases,
        po_probe_max_iter=args.po_probe_max_iter,
        refine_size=args.refine_size,
        refine_strain=args.refine_strain,
        refine_texture=bool(texture),
        texture_lambda=args.texture_lambda,
        refine_aniso=bool(aniso),
        aniso_auto=bool(args.aniso_auto),
        aniso_mode=aniso_mode,
        n_bg=args.n_bg,
        bg_mode=args.bg_mode,
        bg_points=_parse_bg_points(args.bg_points),
        weight_mode=args.weight_mode,
        max_iter=args.max_iter,
        backend=args.backend,
        lm_lambda0=args.lm_lambda,
        lm_step=args.lm_step,
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
            "texture": ({name: {"axis": list(entry.get("axis") or []),
                                "grid": _round_list(entry.get("grid") or [])}
                        for name, entry in (res.params.texture or {}).items()}
                        or None),
            "aniso": ({name: {"size": _round_list(entry.get("size") or []),
                              "strain": _round_list(entry.get("strain") or [])}
                       for name, entry in (res.params.aniso or {}).items()}
                      or None),
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
        runner = RecipeRunner(
            time_budget_s=max(0.0, float(getattr(args, "time_budget_min", 0.0))
                              * 60.0))
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

    # v1.5 M8c：多型建议。只在「ΔB_iso 撞界 + 化学式 + 空间群」三条同时
    # 命中时出现；**不自动替换**输入 CIF（结构模型是实验事实）。
    try:
        from xinrefinement.core.refine.polymorph import suggest as _suggest
        _sug = _suggest(res, inputs.phases)
    except Exception:
        _sug = []
    if _sug:
        print()
        print("## 建议：相结构可能是另一个多型")
        for s in _sug:
            print(f"  - {s.reason}")
            print(f"    候选：{s.candidate.label}"
                  f"（内置 {s.candidate.cif_file}）")
            print(f"    依据：{s.candidate.gain_note}")

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
