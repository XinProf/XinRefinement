"""M0.2 CLI 冒烟测试：refine 子命令 / 裸参数 / JSON / TXT 报告。"""
from __future__ import annotations

import json
from pathlib import Path

from xinrefinement.cli.refine import main

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"


def _common(tmp_path: Path, out_name: str):
    return [
        str(VIRTUAL_B / "v50_wide.xy"),
        str(DATA_CIF / "anatase.cif"),
        str(DATA_CIF / "rutile.cif"),
        "-o", str(tmp_path / out_name),
        "--peak-height",
        "--n-bg", "3",
    ]


def test_cli_refine_json(tmp_path):
    out = tmp_path / "report.json"
    code = main(["refine", *_common(tmp_path, "report.json")])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["r_factors"]["rwp"] < 6.0
    assert len(data["phases"]) == 2
    assert data["fit"]["success"] is True
    assert data["phases"][0]["weight_pct"] is not None


def test_cli_refine_txt_bare_args(tmp_path):
    out = tmp_path / "report.txt"
    code = main(_common(tmp_path, "report.txt"))  # 省略 refine 子命令
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "Rwp" in text
    assert "物相" in text
