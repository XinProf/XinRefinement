"""v1.5 对标报告：把各阶段 JSON 汇成「对 MAUD」的 Markdown 对照表。

数据源全部在 ``C:\\Temp\\maud_compare\\v14``（基准脚本产物，不入 Git）：

===============  =====================================================
base.json        v1.3 基线（5–90°，tent 背景）
combo_tex.json   combo + EWIMV 织构
combo_tex_aniso  combo + EWIMV + Popa LB（M4/M5，v1.5 主线口径）
===============  =====================================================

用法::

    python tools/report_v15.py [--md 输出路径]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUT = Path(r"C:\Temp\maud_compare\v14")
#: MAUD 2.99993 在同一数据集上的 Rwp（读自各 *.par.lst）
MAUD = {1: 10.90, 2: 6.34, 3: 10.29, 4: 9.96, 5: 14.87, 6: 14.76, 7: 11.30}
STAGES = (("base.json", "v1.3 base"),
          ("combo_tex.json", "+EWIMV"),
          ("combo_tex_aniso.json", "+Popa LB（M4/M5）"))


def _load(name: str) -> dict[int, float]:
    p = OUT / name
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8"))
    return {r["i"]: float(r["rwp_pct"]) for r in rows
            if r.get("rwp_pct") is not None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    data = {label: _load(name) for name, label in STAGES}
    labels = [label for _n, label in STAGES]

    head = "| 样品 | MAUD 2 | " + " | ".join(labels) + " | 差距（最优 − MAUD） |"
    sep = "|---" * (len(labels) + 3) + "|"
    lines = [head, sep]
    for i in sorted(MAUD):
        vals = [data[lb].get(i) for lb in labels]
        got = [v for v in vals if v is not None]
        best = min(got) if got else None
        cells = ["—" if v is None else f"{v:.3f}" for v in vals]
        gap = "—" if best is None else f"{best - MAUD[i]:+.2f}"
        lines.append(f"| {i} | {MAUD[i]:.2f} | " + " | ".join(cells)
                     + f" | {gap} |")
    maud_mean = sum(MAUD.values()) / len(MAUD)
    # 均值**逐阶段**算，且注明覆盖样数——不同阶段覆盖的样不同，混算等于造假
    means = []
    for lb in labels:
        vals = list(data[lb].values())
        means.append("—" if not vals
                     else f"{sum(vals) / len(vals):.2f}（{len(vals)}/7）")
    lines.append(f"| **均值** | **{maud_mean:.2f}** | " + " | ".join(means)
                 + " | 见上表逐样差 |")
    text = "\n".join(lines)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n", encoding="utf-8")
        print(f"\n已写入 {a.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
