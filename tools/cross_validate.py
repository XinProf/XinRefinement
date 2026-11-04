"""P4.3 · 与外部精修软件交叉验证（只比结构量）。

对比口径（评审确定的红线）：
- **结构量**（晶胞 a/b/c、相分数）是硬指标，相对差 < 0.5% 视为一致；
- **Rwp/wR** 因实现（背景模型、Kα2 处理、峰形参数化、权重定义）不同，
  仅登记不设门限；
- 参考结果由 ``tools/gsas2_reference.py``（GSAS-II）、FullProf/MAUD/Profex
  的手工导出文件提供，本脚本只读取 JSON，不驱动外部软件。

用法::

    # 1) 先用 GSAS-II 解释器产出参考（一次即可）
    C:/gsas2main/python.exe tools/gsas2_reference.py \
        --pattern "<NCM811.txt>" --cif xinrefinement/data/cif/NCA_80_15_05.cif \
        --out build/crossval/gsas2_ncm811.json

    # 2) 对比并落盘
    python tools/cross_validate.py --pattern "<NCM811.txt>" \
        --cif xinrefinement/data/cif/NCA_80_15_05.cif \
        --reference build/crossval/gsas2_ncm811.json \
        --out docs/CROSS_VALIDATION.md --tmin 10 --tmax 80 --n-bg 4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:      # 直接从 tools/ 运行脚本时保证可 import
    sys.path.insert(0, str(ROOT))

from xinrefinement.core.patterns import load_pattern            # noqa: E402
from xinrefinement.core.profile.cif import parse_cif            # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams    # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig    # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs, solve  # noqa: E402

CELL_REL_TOL = 0.005      # 结构量一致门限：0.5%


def run_ours(pattern: Path, cifs: list[Path], tmin: float, tmax: float,
             n_bg: int) -> dict:
    pat = load_pattern(pattern)
    phases = [parse_cif(c) for c in cifs]
    prm = ProfileParams(anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_cell=True,
                       n_bg=n_bg, tmin=tmin, tmax=tmax, max_iter=60)
    res = solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                             config=cfg))
    return {
        "software": "XinRefinement",
        "wr_pct": float(res.rwp),
        "phases": [{"name": p.name, "cell": [float(v) for v in p.cell]}
                   for p in res.phases],
        "phase_fractions": [p.weight_pct for p in res.phases],
        "success": bool(res.success),
    }


def _rel(a: float, b: float) -> float:
    d = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / d


def compare(ours: dict, ref: dict) -> dict:
    rows = []
    worst = 0.0
    for i, (po, pr) in enumerate(zip(ours["phases"], ref["phases"])):
        diffs = [_rel(a, b) for a, b in zip(po["cell"], pr["cell"])]
        worst = max(worst, max(diffs))
        rows.append({
            "index": i, "name_ours": po["name"], "name_ref": pr["name"],
            "cell_ours": po["cell"], "cell_ref": pr["cell"],
            "max_rel": max(diffs),
        })
    frac = None
    ref_frac = [float(v) for v in (ref.get("phase_fractions") or [])]
    ours_frac = [float(v) for v in (ours.get("phase_fractions") or [])]
    if ref_frac and max(ref_frac) <= 1.5:
        # GSAS-II 的 "Phase fraction" 是 0–1 分数制，我们输出百分数
        ref_frac = [v * 100.0 for v in ref_frac]
    if len(ours_frac) == len(ref_frac) and ref_frac:
        frac = [a - b for a, b in zip(ours_frac, ref_frac)]
    return {
        "rows": rows,
        "worst_cell_rel": worst,
        "cell_pass": worst < CELL_REL_TOL,
        "fraction_diff_pct": frac,
        "wr_pct": {"ours": ours["wr_pct"], "reference": ref["wr_pct"]},
        "tolerance": CELL_REL_TOL,
    }


def to_markdown(cmp: dict, ours: dict, ref: dict, meta: dict) -> str:
    lines = [
        "# 外部软件交叉验证（P4.3）",
        "",
        f"> 生成：`tools/cross_validate.py` ｜ 参考：{ref['software']} ｜ "
        f"窗口 {meta['tmin']:g}–{meta['tmax']:g}°、背景 {meta['n_bg']} 项",
        "",
        "**口径**：结构量（晶胞/相分数）相对差 < 0.5% 判一致；"
        "Rwp/wR 因实现差异仅登记、不设门限。",
        "",
        "## 结构量对比",
        "",
        "| 相 | 量 | XinRefinement | " + ref["software"] + " | 相对差 |",
        "|---|---|---:|---:|---:|",
    ]
    names = ("a", "b", "c", "α", "β", "γ")
    for row in cmp["rows"]:
        for k, (a, b) in enumerate(zip(row["cell_ours"], row["cell_ref"])):
            d = _rel(a, b)
            lines.append(f"| {row['name_ours']} | {names[k]} | {a:.5f} | "
                         f"{b:.5f} | {d * 100:.3f}% |")
    lines += [
        "",
        f"**晶胞最大相对差**：{cmp['worst_cell_rel'] * 100:.3f}% "
        f"（门限 {cmp['tolerance'] * 100:.1f}%）→ "
        f"**{'PASS' if cmp['cell_pass'] else 'FAIL'}**",
        "",
        "## R 因子（仅登记）",
        "",
        "| 软件 | wR / Rwp (%) |",
        "|---|---:|",
        f"| XinRefinement | {cmp['wr_pct']['ours']:.3f} |",
        f"| {ref['software']} | {cmp['wr_pct']['reference']:.3f} |",
        "",
    ]
    if cmp["fraction_diff_pct"] is not None:
        diffs = ", ".join(f"{d:+.3f}pp" for d in cmp["fraction_diff_pct"])
        lines += ["## 相分数（与参考软件差）", "", f"- {diffs}", ""]
    else:
        lines += ["## 相分数", "",
                  "- 单相或参考未给相分数，未比对（多相 QPA 需在 GSAS-II "
                  "GUI 勾选相分数精修，归人工步骤）", ""]
    lines += [
        "## 结论",
        "",
        f"- 结构量：{'一致（< 0.5%）' if cmp['cell_pass'] else '不一致，需排查'}",
        f"- Rwp 差异说明：两套实现背景模型（Chebyshev 项数/归一化）、"
        "Kα2 处理（我们的双线权重 vs GSAS-II 的 I(L2)/I(L1) 参数）、"
        "峰形参数化（Caglioti+TCH vs GSAS-II CW 剖面）不同，"
        "数值不可直接互比。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P4.3 交叉验证（结构量）")
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--cif", nargs="+", required=True)
    ap.add_argument("--reference", required=True, help="参考软件 JSON")
    ap.add_argument("--out", default=str(ROOT / "docs" / "CROSS_VALIDATION.md"))
    ap.add_argument("--tmin", type=float, default=10.0)
    ap.add_argument("--tmax", type=float, default=80.0)
    ap.add_argument("--n-bg", type=int, default=4)
    ap.add_argument("--append", action="store_true",
                    help="追加到已有报告（多案例汇总用）")
    args = ap.parse_args(argv)

    ours = run_ours(Path(args.pattern), [Path(c) for c in args.cif],
                    args.tmin, args.tmax, args.n_bg)
    ref = json.loads(Path(args.reference).read_text(encoding="utf-8"))
    cmp = compare(ours, ref)
    meta = {"tmin": args.tmin, "tmax": args.tmax, "n_bg": args.n_bg}
    md = to_markdown(cmp, ours, ref, meta)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.append and out.exists():
        prev = out.read_text(encoding="utf-8")
        out.write_text(prev + "\n---\n\n" + md, encoding="utf-8")
    else:
        out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n已写入 {out}")
    return 0 if cmp["cell_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
