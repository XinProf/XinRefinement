"""A11：e.s.d. 文本报表「值」列 = 参数真值，e.s.d. 列 = esd。

背景：`_esd_section` 曾用 `zip(esd.labels, esd.esd, esd.esd)`，「值」列与
「e.s.d.」列同源，参数真值从未出现。修复后 `EsdResult.values` 携带 θ=(x,c)
真值，文本/JSON 报表均按 `labels → values → esd` 同序输出。
"""
from __future__ import annotations

import numpy as np

from xinrefinement.cli.refine import _esd_json_dict, _esd_section
from xinrefinement.core.refine.esd import EsdResult


def _mk_esd() -> EsdResult:
    labels = ("global.zero", "phase[A].micro.X", "scale[0]", "bg[0]")
    values = (0.0123, 0.0, 1.5e-2, 42.0)
    esd = (0.0004, float("nan"), 2.0e-3, 0.7)   # 第 2 个是 TCH 边界 NaN
    n = len(labels)
    return EsdResult(
        labels=labels, values=values, esd=esd,
        covariance=np.eye(n), correlation=np.eye(n),
        scale_esd=(2.0e-3,), weight_esd_pct=None,
        variance_factor=1.5, schur_consistency=0.01,
        n_points=1000, n_params=n)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def test_esd_section_value_column_is_parameter_value():
    esd = _mk_esd()
    rows = [r for r in _esd_section(esd)
            if r.startswith("| ") and "参数" not in r and "---" not in r]
    got = {_cells(r)[0]: _cells(r)[1:] for r in rows}

    # 值列 == 参数真值；e.s.d. 列 == esd（不是同一个数）
    assert got["global.zero"] == [f"{0.0123:.6g}", "±0.0004"]
    assert got["scale[0]"] == [f"{1.5e-2:.6g}", "±0.002"]
    assert got["bg[0]"] == [f"{42.0:.6g}", "±0.7"]
    # TCH 边界：值列显示真实值（0），e.s.d. 列显示边界标注
    assert got["phase[A].micro.X"] == [f"{0.0:.6g}", "—（TCH 边界，无定义）"]
    # 防止复现旧 bug：值列不能等于 e.s.d.
    assert got["global.zero"][0] != got["global.zero"][1].lstrip("±")


def test_esd_json_has_values_matching_labels():
    esd = _mk_esd()
    d = _esd_json_dict(esd)
    assert list(d)[:3] == ["labels", "values", "esd"]
    assert len(d["values"]) == len(d["labels"]) == len(d["esd"])
    # 值列 = 参数值（round 6）；e.s.d. 列 NaN -> None；边界参数的值仍是 0 而非 None
    assert d["values"][0] == round(0.0123, 6)
    assert d["esd"][1] is None
    assert d["values"][1] == round(0.0, 6)
