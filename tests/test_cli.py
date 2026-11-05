"""M0.2 CLI 冒烟测试：refine 子命令 / 裸参数 / JSON / TXT 报告。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    # CLI 与 solve 同口径，同样锁定 golden 数值
    assert data["r_factors"]["rwp"] == pytest.approx(3.409617, abs=0.01)
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


def test_cli_grain_size_auto_mur(tmp_path):
    """v1.3：--grain-size 按成分自动算 μ·r 进引擎。

    简并不变量：Brindley 因子被每相 scale 完全吸收 → Rwp **逐位不变**；
    校正作用于 QPA —— 高 μ 相 wt% 被抬升（微吸收压低表观含量的纠正方向）。
    """
    out = tmp_path / "auto.json"
    argv = _common(tmp_path, "auto.json") + ["--grain-size", "anatase=5.0"]
    assert main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    out0 = tmp_path / "base.json"
    assert main(_common(tmp_path, "base.json")) == 0
    base = json.loads(out0.read_text(encoding="utf-8"))
    # Rwp 简并不变（与 core 引擎同口径的数学事实）
    assert data["r_factors"]["rwp"] == base["r_factors"]["rwp"]
    # wt% 被校正（锐钛矿 μ·r≈0.24，wt% 抬升）
    wa = next(p for p in data["phases"] if p["name"] == "anatase")
    wb = next(p for p in base["phases"] if p["name"] == "anatase")
    assert wa["weight_pct"] > wb["weight_pct"]
