""".xinm 导入（联合计划 R-1 / R-5）+ .xinr zip 容器（R-2 / R-6）。

.xinm 样例直接按 docs/JOINT_PLAN_xinm_xinr.md §2.1 的容器契约在 tmp 里构造，
不依赖 XinMatch 安装；另有一条真实 XinMatch 导出器的联调用例（可跳过）。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.io.xinm_import import (
    SUPPORTED_XINM_VERSION,
    XinmImportError,
    extract_cifs,
    read_xinm,
)


# --------------------------------------------------------------------------- #
# fixture：手工构造 .xinm
# --------------------------------------------------------------------------- #
def _manifest() -> dict:
    return {
        "format": "xinm", "version": 1,
        "created": "2026-11-05T12:00:00",
        "app": {"name": "XinMatch", "version": "3.4.0"},
        "pattern": {"file": "pattern/pattern.csv",
                    "source_path": "D:/data/demo.xy",
                    "wavelength": 1.5406, "anode": "Cu",
                    "tmin": 5.0, "tmax": 90.0, "step": 0.5,
                    "metadata": {"sample": "demo"}},
        "peaks": [{"two_theta": 25.3, "d": 3.52, "intensity": 100.0,
                   "hkl": [1, 0, 1]}],
        "phases": [
            {"name": "anatase", "source": "cod", "entry_id": "96-400-1849",
             "cif_file": "cifs/4001849.cif", "structural": True, "reason": "",
             "fom": None, "scale_factor": 1.25, "two_theta_shift": 0.0,
             "weight_fraction": 0.52,
             "cell": {"a": 3.785, "b": 3.785, "c": 9.5196, "alpha": 90.0,
                      "beta": 90.0, "gamma": 90.0},
             "space_group": "I41/amd", "formula": "O2 Ti",
             "mineral_name": "anatase"},
            {"name": "pdf2card", "source": "pdf2", "entry_id": "01-070-1234",
             "cif_file": None, "structural": False,
             "reason": "ICDD 条目无结构数据", "fom": None,
             "scale_factor": 1.0, "two_theta_shift": 0.0,
             "weight_fraction": None, "cell": None,
             "space_group": "P4_2/mnm", "formula": "O2 Ti",
             "mineral_name": None},
        ],
        "candidates_summary": [{"name": "brookite", "entry_id": "96-201-1664",
                                "source": "cod", "cif_file": None}],
        "restraints": {}, "notes": "",
    }


@pytest.fixture()
def xinm_path(tmp_path: Path) -> Path:
    out = tmp_path / "analysis.xinm"
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        buf = ["two_theta,intensity"]
        buf += [f"{x:.10g},{y:.10g}" for x, y in zip(tt.tolist(), ii.tolist())]
        zf.writestr("pattern/pattern.csv", "\n".join(buf))
        zf.writestr("cifs/4001849.cif",
                    "data_4001849\n_cell_length_a 3.785\n")
        zf.writestr("manifest.json",
                    json.dumps(_manifest(), ensure_ascii=False, indent=2))
    return out


# --------------------------------------------------------------------------- #
# read_xinm
# --------------------------------------------------------------------------- #
def test_read_xinm_roundtrip(xinm_path: Path) -> None:
    payload = read_xinm(xinm_path)
    assert payload.two_theta.size == 171
    assert payload.meta["wavelength"] == pytest.approx(1.5406)
    assert payload.meta["anode"] == "Cu"
    assert len(payload.phases) == 2
    assert len(payload.structural_phases) == 1
    assert len(payload.reference_only_phases) == 1
    ref = payload.reference_only_phases[0]
    assert ref.name == "pdf2card"
    assert ref.source == "pdf2"
    assert "cifs/4001849.cif" in payload.cif_bytes
    assert payload.peaks[0]["two_theta"] == 25.3


def test_extract_cifs_writes_files(xinm_path: Path, tmp_path: Path) -> None:
    payload = read_xinm(xinm_path)
    mapping = extract_cifs(payload, tmp_path / "cifs_out")
    assert set(mapping) == {"anatase"}
    p = mapping["anatase"]
    assert p.is_file() and p.suffix == ".cif"
    assert "data_4001849" in p.read_text(encoding="utf-8")


def test_read_xinm_rejects_non_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xinm"
    bad.write_text("not a zip", encoding="utf-8")
    with pytest.raises(XinmImportError, match="不是有效"):
        read_xinm(bad)


def test_read_xinm_rejects_wrong_format(tmp_path: Path) -> None:
    p = tmp_path / "x.xinm"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "other", "version": 1}))
    with pytest.raises(XinmImportError, match="不是 xinm"):
        read_xinm(p)


def test_read_xinm_rejects_future_version(tmp_path: Path) -> None:
    p = tmp_path / "x.xinm"
    m = _manifest()
    m["version"] = SUPPORTED_XINM_VERSION + 1
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(m))
        zf.writestr("pattern/pattern.csv", "two_theta,intensity\n1,2\n3,4\n")
    with pytest.raises(XinmImportError, match="高于本程序支持"):
        read_xinm(p)


def test_read_xinm_zip_bomb_guard(xinm_path: Path) -> None:
    """守卫逻辑：解压内容超过上限即拒绝（用极小上限等价验证）。"""
    with pytest.raises(XinmImportError, match="超过上限"):
        read_xinm(xinm_path, max_total_bytes=10)


def test_read_xinm_bad_csv(tmp_path: Path) -> None:
    p = tmp_path / "x.xinm"
    m = _manifest()
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(m))
        zf.writestr("pattern/pattern.csv", "two_theta,intensity\n5,a\n")
    with pytest.raises(XinmImportError, match="无法解析"):
        read_xinm(p)


# --------------------------------------------------------------------------- #
# 与 XinMatch 真实导出器的联调（XinMatch 可导入时执行）
# --------------------------------------------------------------------------- #
def test_roundtrip_with_real_xinmatch_exporter(tmp_path: Path) -> None:
    """构造最小 Project 走 XinMatch export_xinm → 本项目 read_xinm。"""
    try:
        from xinmatch.core.io.xinm import export_xinm
        from xinmatch.core.model.entry import CellParams, Entry
        from xinmatch.core.model.pattern import Pattern as XmPattern
        from xinmatch.core.model.phase import Phase
        from xinmatch.core.model.project import Project
    except ImportError:
        pytest.skip("XinMatch 不在 import 路径上")
    cod_root = tmp_path / "cod"
    d = cod_root / "4" / "00" / "18"
    d.mkdir(parents=True)
    (d / "4001849.cif").write_text("data_4001849\n", encoding="utf-8")
    n = 100
    xm_pat = XmPattern(two_theta=np.linspace(5, 90, n),
                       intensity=np.linspace(10, 20, n),
                       wavelength=1.5406)
    entry = Entry(entry_id="96-400-1849", formula="O2 Ti",
                  d_spacings=np.array([3.52]), intensities=np.array([1000.0]),
                  mineral_name="anatase",
                  cell=CellParams(3.785, 3.785, 9.5196, 90, 90, 90),
                  space_group="I41/amd")
    proj = Project(patterns=[xm_pat],
                   selected_phases=[Phase(entry=entry, scale_factor=1.25)])
    out = tmp_path / "joint.xinm"
    export_xinm(proj, out, cod_root=cod_root, app_version="3.4.0-test")

    payload = read_xinm(out)
    assert payload.two_theta.size == n
    assert payload.two_theta == pytest.approx(
        np.linspace(5, 90, n), rel=1e-9)
    assert len(payload.structural_phases) == 1
    assert payload.structural_phases[0].name == "anatase"
