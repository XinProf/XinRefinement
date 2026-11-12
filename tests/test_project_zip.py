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

    # 内嵌谱图数值往返（%.17g 写出，逐位保真；此处仍用 rel ≤ 1e-9 近似断言）
    tt = np.loadtxt(data["pattern"])
    assert tt.shape == (171, 2)
    assert tt[:, 0] == pytest.approx(
        np.linspace(5.0, 90.0, 171), rel=1e-9)


def test_save_xinr_embeds_full_result_json(workdir: Path) -> None:
    """R-2a：完整精修结果写 result/refine.json，并在重开后读回。"""
    full = {
        "input": {"pattern": "demo.xy", "cif": ["anatase.cif"],
                  "tmin": 5.0, "tmax": 90.0, "anode": "Cu"},
        "r_factors": {"rwp": 3.409617, "rp": 2.5, "rexp": 2.0,
                      "chi2": 2.9, "rbragg": 1.2},
        "fit": {"success": True, "iters": 12, "restarted": False},
        "parameters": {"zero": 0.0, "U": 0.01, "wavelength": 1.5406},
        "background": [1.0, 2.0],
        "phases": [{"name": "anatase", "scale": 1.0, "weight_pct": 50.03,
                    "cell": [3.785, 3.785, 9.5196, 90, 90, 90]}],
        "rwp_history": [10.0, 5.0, 3.409617],
        "diagnostics": {"dw": 1.9, "verdict": "ok", "rwp_start": 10.0,
                        "rwp_final": 3.409617},
        "esd": {"labels": ["zero"], "esd": [0.001],
                "weight_esd_pct": [0.12]},
        "warnings": [],
    }
    state = {
        "language": "zh", "pattern": str(workdir / "demo.xy"),
        "cifs": [str(workdir / "anatase.cif")],
        "settings": {}, "phase_edits": {},
        "result": {"rwp": 3.409617}, "result_full": full, "navigation": {},
    }
    out = workdir / "full.xinr"
    save_project(state, out, embed=True)
    with zipfile.ZipFile(out) as zf:
        assert "result/refine.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["result_full"] == "result/refine.json"
    data = load_project(out)
    assert data["result_full"]["r_factors"]["rwp"] == pytest.approx(3.409617)
    assert data["result_full"]["phases"][0]["weight_pct"] == pytest.approx(50.03)
    # 旧摘要仍在，供 v1.0.0 风格读取
    assert data["result"] == {"rwp": 3.409617}


def test_load_xinr_without_result_full_is_tolerated(workdir: Path) -> None:
    """无 result_full 的工程（如未精修）读回应为 None，不报错。"""
    state = {
        "language": "zh", "pattern": str(workdir / "demo.xy"),
        "cifs": [], "settings": {}, "phase_edits": {},
        "result": None, "navigation": {},
    }
    out = workdir / "empty.xinr"
    save_project(state, out, embed=True)
    data = load_project(out)
    assert data["result_full"] is None


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


# --------------------------------------------------------------------------- #
# A08：result/refine.json 解码失败必须露出告警
# --------------------------------------------------------------------------- #
def _write_xinr_with_raw_result(p: Path, payload: bytes) -> Path:
    """手工造 .xinr：manifest 声明了 result_full，但成员内容是坏数据。"""
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "language": "zh", "settings": {}, "phase_edits": {},
        "result": {"rwp": 3.409617}, "result_full": "result/refine.json",
        "navigation": {}, "pattern": {}, "cifs": [],
    }
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("result/refine.json", payload)
    return p


def test_load_xinr_bad_result_json_reports_warning(workdir: Path) -> None:
    p = _write_xinr_with_raw_result(workdir / "badjson.xinr", b"{not json")
    data = load_project(p)
    assert data["result_full"] is None
    assert data["warnings"]
    assert "refine.json" in data["warnings"][0]


def test_load_xinr_non_utf8_result_json_reports_warning(workdir: Path) -> None:
    p = _write_xinr_with_raw_result(workdir / "badutf8.xinr", b"\xff\xfe\x00bad")
    data = load_project(p)
    assert data["result_full"] is None
    assert data["warnings"]
    assert "refine.json" in data["warnings"][0]


def test_all_load_paths_expose_warnings_key(workdir: Path) -> None:
    ok = workdir / "ok.xinr"
    save_project({"language": "zh", "pattern": str(workdir / "demo.xy"),
                  "cifs": [], "settings": {}, "phase_edits": {},
                  "result": None, "navigation": {}}, ok, embed=True)
    assert load_project(ok)["warnings"] == []

    legacy = workdir / "ok.xrp"
    save_project({"language": "zh", "pattern": str(workdir / "demo.xy"),
                  "cifs": [], "settings": {}, "phase_edits": {},
                  "result": None, "navigation": {}}, legacy, embed=False)
    assert load_project(legacy)["warnings"] == []

