"""`.xinr` zip 容器 / 旧 `.xrp` 兼容（联合计划 R-2 / R-6）。"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.gui.project import (
    FORMAT,
    FORMAT_VERSION,
    load_project,
    save_project,
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    """谱图 + CIF + 旧 .xrp 三件套。"""
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)
    xy = tmp_path / "demo.xy"
    xy.write_text(
        "\n".join(f"{x:.10g} {y:.10g}" for x, y in zip(tt, ii)),
        encoding="utf-8")
    cif = tmp_path / "anatase.cif"
    cif.write_text(
        "data_anatase\n_cell_length_a 3.785\n"
        "_cell_length_b 3.785\n_cell_length_c 9.5196\n"
        "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n",
        encoding="utf-8")
    state = {
        "language": "zh",
        "pattern": str(xy),
        "cifs": [str(cif)],
        "settings": {"n_bg": 3},
        "phase_edits": {"anatase": {"cell": [3.79, 3.79, 9.52, 90, 90, 90],
                                    "po": None}},
        "result": {"rwp": 3.409617},
        "navigation": {"step_status": {"background": "done"}},
    }
    return tmp_path


# --------------------------------------------------------------------------- #
# 新格式 .xinr（zip 容器）
# --------------------------------------------------------------------------- #
def test_save_xinr_zip_and_reopen(workdir: Path) -> None:
    state = {
        "language": "zh", "pattern": str(workdir / "demo.xy"),
        "cifs": [str(workdir / "anatase.cif")],
        "settings": {"n_bg": 3},
        "phase_edits": {"anatase": {"cell": [3.79, 3.79, 9.52, 90, 90, 90],
                                    "po": None}},
        "result": {"rwp": 3.409617},
        "navigation": {"step_status": {"background": "done"}},
    }
    out = workdir / "proj.xinr"
    save_project(state, out, embed=True)
    assert out.is_file()
    assert out.open("rb").read(2) == b"PK"       # zip 容器

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "pattern/pattern.csv"} <= names
        assert any(n.startswith("cifs/") for n in names)
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["format"] == FORMAT
    assert manifest["format_version"] == FORMAT_VERSION
    assert manifest["phase_edits"]["anatase"]["cell"][0] == 3.79

    # 关键验收：把外部源文件移走后仍能打开（自包含）
    (workdir / "demo.xy").rename(workdir / "demo_moved.xy")
    (workdir / "anatase.cif").rename(workdir / "anatase_moved.cif")
    data = load_project(out)
    assert data["embedded"] is True
    assert data["missing"] == []
    assert data["pattern"] and Path(data["pattern"]).is_file()
    assert len(data["cifs"]) == 1 and Path(data["cifs"][0]).is_file()
    assert data["settings"] == {"n_bg": 3}
    assert data["result"] == {"rwp": 3.409617}

    # 内嵌谱图数值往返（%.10g，rel ≤ 1e-9）
    tt = np.loadtxt(data["pattern"])
    assert tt.shape == (171, 2)
    assert tt[:, 0] == pytest.approx(
        np.linspace(5.0, 90.0, 171), rel=1e-9)


def test_load_xinr_future_version_rejected(workdir: Path) -> None:
    out = workdir / "future.xinr"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("manifest.json", json.dumps(
            {"format": FORMAT, "format_version": FORMAT_VERSION + 1}))
    with pytest.raises(ValueError, match="高于本程序支持"):
        load_project(out)


# --------------------------------------------------------------------------- #
# 旧格式 .xrp（JSON 路径引用）——永久只读兼容
# --------------------------------------------------------------------------- #
def test_save_legacy_xrp_and_reopen(workdir: Path) -> None:
    state = {
        "language": "zh", "pattern": str(workdir / "demo.xy"),
        "cifs": [str(workdir / "anatase.cif")],
        "settings": {"n_bg": 3}, "phase_edits": {},
        "result": None, "navigation": {},
    }
    out = workdir / "proj.xrp"
    save_project(state, out, embed=False)
    assert out.open("rb").read(2) != b"PK"
    data = load_project(out)
    assert data["embedded"] is False
    assert data["missing"] == []
    assert Path(data["pattern"]).is_file()
    assert data["pattern"].endswith("demo.xy")


def test_load_legacy_v1_xrp_compat(workdir: Path) -> None:
    """v1.0.0 手写的旧 .xrp（无 phase_edits/embedded 字段）能读。"""
    legacy = {
        "format": FORMAT, "format_version": 1,
        "app_version": "1.0.0", "language": "zh",
        "pattern": "demo.xy", "cifs": ["anatase.cif"],
        "settings": {}, "result": None, "navigation": {},
    }
    p = workdir / "legacy.xrp"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    data = load_project(p)
    assert data["missing"] == []
    assert data["phase_edits"] == {}
    assert data["embedded"] is False


def test_load_corrupt_zip_raises(workdir: Path) -> None:
    p = workdir / "corrupt.xinr"
    p.write_bytes(b"PK\x03\x04garbage")
    with pytest.raises(ValueError, match="损坏"):
        load_project(p)
