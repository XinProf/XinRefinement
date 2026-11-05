"""P4.1 · 精修报告导出（core 层，无 GUI 依赖）。

参考 Profex 的结构化报告：HTML（含拟合图、R 因子表、参数表、物相表、
收敛摘要、诊断量与 e.s.d.）+ PNG 拟合图 + JSON 精修日志（可复现）。

设计：所有绘制/序列化集中在 core，GUI 与 CLI 只调 ``export_report``，
保证「界面里长什么样，报告里就长什么样」（与色板同源）。
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from xinrefinement.core.palette import DEFAULT_STYLE, apply_axis_style
from xinrefinement.core.refine.diagnostics import diagnose
from xinrefinement.core.refine.solve import SolveResult

STYLE = DEFAULT_STYLE


def _plot_png(res: SolveResult, path: Path) -> str:
    """离屏绘制 obs/calc/diff 双轴图（Agg 后端，不依赖 Qt）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tt, yo, yc = (res.pattern.two_theta, res.pattern.intensity, res.ycalc)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 5), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]}, layout="constrained")
    ax1.plot(tt, yo, linestyle="none", marker="x", color=STYLE.obs,
             markersize=3, markeredgewidth=0.6, label="Observed")
    ax1.plot(tt, yc, color=STYLE.calc, lw=1.0, label="Calculated")
    ax1.set_ylabel("Intensity (cts)")
    ax1.legend(loc="upper right", fontsize=8, frameon=False)
    apply_axis_style(ax1)
    ax1.tick_params(labelbottom=False)
    ax2.plot(tt, yo - yc, color=STYLE.diff, lw=0.8)
    ax2.axhline(0, color=STYLE.grid, lw=0.6)
    ax2.set_xlabel("2theta (deg)")
    ax2.set_ylabel("Difference")
    apply_axis_style(ax2)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path.name


def _log_dict(res: SolveResult, diagnostics, esd=None) -> dict:
    prm = res.params
    return {
        "r_factors": {"rwp": res.rwp, "rp": res.rp, "rexp": res.rexp,
                      "chi2": res.chi2, "rbragg": res.rbragg},
        "fit": {"success": res.success, "iters": res.iters,
                "restarted": res.restarted},
        "parameters": {
            "zero": prm.zero, "U": prm.U, "V": prm.V, "W": prm.W,
            "eta": prm.eta, "asym": prm.asym, "bfactor": prm.bfactor,
            "X": prm.X, "Y": prm.Y, "anode": prm.anode,
            "wavelength": prm.wavelength,
        },
        "phases": [{"name": p.name, "scale": p.scale,
                    "weight_pct": p.weight_pct, "cell": list(p.cell)}
                   for p in res.phases],
        "rwp_history": list(res.history),
        "diagnostics": asdict(diagnostics),
        "esd": (None if esd is None else
                {"labels": list(esd.labels), "esd": list(esd.esd),
                 "weight_esd_pct": list(esd.weight_esd_pct)
                 if esd.weight_esd_pct else None,
                 "schur_consistency": esd.schur_consistency}),
        "warnings": list(res.warnings),
    }


def solve_result_dict(res: SolveResult, *, esd=None,
                      input_info: dict | None = None) -> dict:
    """完整精修结果 JSON（与 CLI ``--out`` / ``export_report`` 同族 schema）。

    GUI 保存 ``.xinr`` 时把本函数结果写入 ``result/refine.json``（联合计划
    R-2a），使工程文件自带可与 CLI 报告对照的完整精修记录，而不只是
    R 因子摘要。``input_info`` 非空时置于 ``input`` 段（CLI 报告同位置）。
    """
    data = _log_dict(res, diagnose(res), esd)
    if input_info is not None:
        data = {"input": dict(input_info), **data}
    return data


def _html(res: SolveResult, diagnostics, png_name: str, esd=None) -> str:
    esc = html.escape

    def row(k, v):
        return f"<tr><th>{esc(str(k))}</th><td>{esc(str(v))}</td></tr>"

    prm = res.params
    params_rows = "".join(
        row(k, f"{v:.6g}" if isinstance(v, float) else v)
        for k, v in (("zero", prm.zero), ("U", prm.U), ("V", prm.V),
                     ("W", prm.W), ("eta", prm.eta), ("asym", prm.asym),
                     ("bfactor", prm.bfactor), ("X (strain)", prm.X),
                     ("Y (size)", prm.Y), ("anode", prm.anode),
                     ("wavelength (A)", prm.wavelength)))
    phase_rows = "".join(
        f"<tr><td>{esc(p.name)}</td><td>{p.scale:.6g}</td>"
        f"<td>{'—' if p.weight_pct is None else f'{p.weight_pct:.3f}'}</td>"
        f"<td>{p.volume:.2f}</td></tr>" for p in res.phases)
    esd_html = ""
    if esd is not None and esd.weight_esd_pct:
        esd_html = "<h2>物相含量 e.s.d.</h2><table><tr><th>相</th><th>含量 (%)</th><th>e.s.d. (pp)</th></tr>" + "".join(
            f"<tr><td>{esc(p.name)}</td>"
            f"<td>{'—' if p.weight_pct is None else f'{p.weight_pct:.3f}'}</td>"
            f"<td>{e:.4f}</td></tr>"
            for p, e in zip(res.phases, esd.weight_esd_pct)) + "</table>"
    warn = ("<h2>警告</h2><ul>" + "".join(f"<li>{esc(w)}</li>"
                                        for w in res.warnings) + "</ul>") \
        if res.warnings else ""
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>XinRefinement 精修报告</title>
<style>
body{{font-family:"Segoe UI","Microsoft YaHei",sans-serif;max-width:960px;
margin:2rem auto;padding:0 1rem;color:#222;line-height:1.55}}
h1{{font-size:1.5rem;border-bottom:2px solid #1f77b4;padding-bottom:.4rem}}
h2{{font-size:1.1rem;margin-top:1.6rem;color:#1f77b4}}
table{{border-collapse:collapse;width:100%;margin:.6rem 0}}
th,td{{border:1px solid #ddd;padding:.35rem .6rem;text-align:left;font-size:.9rem}}
th{{background:#f5f7fa;font-weight:500}}
img{{max-width:100%;border:1px solid #eee}}
.meta{{color:#666;font-size:.85rem}}
</style></head><body>
<h1>XinRefinement 全谱拟合报告</h1>
<p class="meta">Rietveld refinement · 窗口 [{res.config.tmin:g}, {res.config.tmax:g}]°
 · {res.pattern.two_theta.size} 数据点</p>
<h2>拟合优度</h2><table>
{row('Rwp (%)', f'{res.rwp:.4f}')}{row('Rp (%)', f'{res.rp:.4f}')}
{row('Rexp (%)', f'{res.rexp:.4f}')}{row('chi2', f'{res.chi2:.4f}')}
{row('收敛', res.success)}{row('迭代评估次数', res.iters)}
{row('Durbin-Watson', f'{diagnostics.dw:.4f}')}
{row('残差判读', diagnostics.verdict)}
</table>
<h2>拟合图谱</h2><img src="{esc(png_name)}" alt="fit">
<h2>精修参数</h2><table>{params_rows}</table>
<h2>物相</h2><table><tr><th>相</th><th>scale</th><th>质量分数 (%)</th>
<th>晶胞体积 (A^3)</th></tr>{phase_rows}</table>
{esd_html}{warn}
<h2>收敛摘要</h2><table>
{row('Rwp 起始', f'{diagnostics.rwp_start:.4f}')}
{row('Rwp 最终', f'{diagnostics.rwp_final:.4f}')}
{row('Rwp 下降', f'{diagnostics.rwp_drop:.4f}')}
{row('残差评估次数', diagnostics.n_evals)}
{row('残差 RMS', f'{diagnostics.residual_rms:.2f}')}
</table></body></html>"""


def export_report(res: SolveResult, out_dir: str | Path,
                  stem: str = "refine_report", esd=None) -> dict[str, str]:
    """导出 HTML + PNG + JSON 日志，返回 {kind: path}。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    diagnostics = diagnose(res)
    png = _plot_png(res, out / f"{stem}.png")
    html_path = out / f"{stem}.html"
    html_path.write_text(_html(res, diagnostics, png, esd), encoding="utf-8")
    log_path = out / f"{stem}.json"
    log_path.write_text(json.dumps(_log_dict(res, diagnostics, esd),
                                   ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"html": str(html_path), "png": str(out / png),
            "json": str(log_path)}
