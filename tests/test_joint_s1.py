"""S1 端到端闭环（联合计划 §5）：XinMatch 导出 → 导入 → 精修 → 自包含 .xinr。

链路全走真实档案（COD 7206075 / 9001681）+ 真实引擎，不是桩数据：

1. 以 ``tests/data/virtual_b/v50_wide.xy``（TiO2 50/50 合成样）建 XinMatch 工程，
   两个 COD 相走 ``export_xinm`` → ``.xinm``（内含 CIF）。
2. ``.xinr`` 侧：``_apply_xinm_payload`` 导入 → 一键连跑 → Rwp_A。
3. 手动路径：同一谱图 + 同一 CIF 直接装载 → 一键连跑 → Rwp_B。
   **断言 Rwp_A == Rwp_B**（同一代码路径，导入不引入任何偏差）。
4. 保存 ``.xinr``，删除临时源谱图与 ``.xinm`` 后重新打开 → 谱图/CIF 自包含
   → 再跑一次 → Rwp_C == Rwp_A（复现性）。

COD 档案或 XinMatch 不可用时整文件跳过（CI 无档案场景）。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

COD_ROOT = Path("D:/Project/XRD/sync-COD/COD")
ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"

pytestmark = pytest.mark.skipif(
    not (COD_ROOT.is_dir() and PATTERN.is_file()),
    reason="需要本机 COD 档案与合成谱样例")


@pytest.fixture(scope="session")
def xm_api():
    try:
        from xinmatch.core.io.xinm import export_xinm
        from xinmatch.core.model.entry import CellParams, Entry
        from xinmatch.core.model.pattern import Pattern as XmPattern
        from xinmatch.core.model.phase import Phase
        from xinmatch.core.model.project import Project
    except ImportError as exc:  # pragma: no cover
        # 不要把理由写死成「不在 import 路径上」——2026-11-07 实测真因是
        # 缺 gemmi（XinMatch 的依赖），路径本身是好的，误导了很久
        pytest.skip(f"XinMatch 不可用：{exc}")
    return {"export_xinm": export_xinm, "CellParams": CellParams,
            "Entry": Entry, "XmPattern": XmPattern, "Phase": Phase,
            "Project": Project}


def _load_xy(path: Path):
    import numpy as np
    arr = np.loadtxt(path)
    return arr[:, 0], arr[:, 1]


def _export_real_xinm(tmp_path: Path, xm_api) -> Path:
    """真实 COD 双相 → .xinm（CIF 走 cif_store 真实回取）。"""
    from xinrefinement.core.profile.cif import parse_cif

    tt, ii = _load_xy(PATTERN)
    pat = xm_api["XmPattern"](two_theta=tt, intensity=ii, wavelength=1.5406)
    phases = []
    for ref_id in ("96-720-6075", "96-900-1681"):
        cod_id = ref_id.split("-")[1] + ref_id.split("-")[2]
        st = parse_cif(COD_ROOT / cod_id[0] / cod_id[1:3] / cod_id[3:5]
                       / f"{cod_id}.cif")
        entry = xm_api["Entry"](
            entry_id=ref_id, formula=st.formula or "",
            d_spacings=__import__("numpy").array([3.52]),
            intensities=__import__("numpy").array([1000.0]),
            mineral_name=None,
            cell=xm_api["CellParams"](*st.cell),
            space_group=st.spacegroup)
        phases.append(xm_api["Phase"](entry=entry, scale_factor=1.0))
    proj = xm_api["Project"](patterns=[pat], selected_phases=phases)
    out = tmp_path / "s1.xinm"
    xm_api["export_xinm"](proj, out, cod_root=COD_ROOT,
                          app_version="3.4.0")
    return out


def _rwp_after_recipe(win, qapp) -> float:
    win.run_recipe_all()
    assert win.wait_for_worker(180000) is True
    qapp.processEvents()
    assert win._result is not None
    return float(win._result.rwp)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


def test_s1_api_path_reproduces_golden_rwp(tmp_path, xm_api):
    """导入后的谱图 + CIF 走公开 API，Rwp 复现当前黄金值（3.407416）。

    这是 S1 的"数值保真"证据：``.xinm`` 的 CSV ``%.10g`` 往返与 CIF 打包
    没有引入任何可测偏差（黄金值为 CLI/API 口径，见 test_solve）。

    注：本用例在 2026-11-07 之前**恒被 skip**（缺 `gemmi` → fixture 跳过），
    因此 M11（`17525bb` 窗口边界峰外扩 + 结构因子向量化）把数值从
    ``3.409617019598457`` 改到 ``3.4074156640940005`` 后没人发现。现在与
    ``tests/golden/method_b_roundtrip.json`` 的 50/50 档严格同值。"""
    from xinrefinement import api as api_mod
    from xinrefinement.core.io.xinm_import import extract_cifs, read_xinm

    payload = read_xinm(_export_real_xinm(tmp_path, xm_api))
    cifs = extract_cifs(payload, tmp_path / "cif_out")
    xy = tmp_path / "pattern.xy"
    with xy.open("w", encoding="utf-8", newline="\n") as fh:
        for x, y in zip(payload.two_theta.tolist(),
                        payload.intensity.tolist()):
            fh.write(f"{x:.10g} {y:.10g}\n")
    res = api_mod.refine(api_mod.RefineRequest(
        pattern=xy, cifs=tuple(cifs.values()), peak_height=True))
    assert res.rwp == pytest.approx(3.4074156640940005, rel=1e-12)
    assert {p["name"] for p in res.phases} == {"7206075", "9001681"}
    assert all(40.0 < p["weight_pct"] < 60.0 for p in res.phases)


def test_s1_full_loop_matches_manual_import(tmp_path, qapp, xm_api):
    from xinrefinement.core.io.xinm_import import read_xinm
    from xinrefinement.gui.main_window import MainWindow
    from xinrefinement.gui.project import load_project, save_project

    xinm = _export_real_xinm(tmp_path, xm_api)
    payload = read_xinm(xinm)
    assert len(payload.structural_phases) == 2, "两相 CIF 都应从 COD 回取成功"

    # --- 路径 A：.xinm 导入 → 一键连跑 ---
    win_a = MainWindow()
    try:
        report = win_a._apply_xinm_payload(payload, stem="s1")
        assert report is not None and len(win_a._phases) == 2
        rwp_a = _rwp_after_recipe(win_a, qapp)
        assert rwp_a < 10.0
        wt_a = {ph.name: ph.weight_pct for ph in win_a._result.phases}
        # 50/50 合成样：定量应落在 50% 附近
        for name, wt in wt_a.items():
            assert 40.0 < wt < 60.0, (name, wt)

        # --- 保存自包含 .xinr ---
        state = win_a.project_state()
        assert state["result_full"] is not None
        proj = tmp_path / "s1.xinr"
        save_project(state, proj, embed=True)
    finally:
        win_a.close()
        qapp.processEvents()

    # --- 移走可移动的外部输入（谱图副本与 .xinm），验证自包含 ---
    session_xy = Path(win_a._pattern_path) if win_a._pattern_path else None
    xinm.unlink()
    if session_xy and session_xy.is_file() and session_xy.parent.name == \
            "xinrefinement_xinm":
        shutil.rmtree(session_xy.parent, ignore_errors=True)

    # --- 路径 B：打开 .xinr → 再跑一次 → 复现 Rwp ---
    data = load_project(proj)
    assert data["missing"] == []
    assert data["pattern"] and Path(data["pattern"]).is_file()
    assert len(data["cifs"]) == 2
    win_b = MainWindow()
    try:
        win_b.apply_project(data)
        qapp.processEvents()
        assert win_b._pattern is not None and len(win_b._phases) == 2
        rwp_b = _rwp_after_recipe(win_b, qapp)
    finally:
        win_b.close()
        qapp.processEvents()
    assert rwp_b == pytest.approx(rwp_a, rel=1e-9), (rwp_a, rwp_b)


def test_s1_manual_path_same_rwp(tmp_path, qapp, xm_api):
    """同一谱图 + 同一 CIF 的手动装载，Rwp 与 .xinm 导入逐位一致。"""
    from xinrefinement.core.io.xinm_import import read_xinm
    from xinrefinement.gui.main_window import MainWindow

    xinm = _export_real_xinm(tmp_path, xm_api)
    payload = read_xinm(xinm)

    win_a = MainWindow()
    try:
        win_a._apply_xinm_payload(payload, stem="s1m")
        rwp_xinm = _rwp_after_recipe(win_a, qapp)
    finally:
        win_a.close()
        qapp.processEvents()

    # 手动：把 COD 档案 CIF 直接交给 GUI（与 XinMatch 回取的同一份文件）
    tt, ii = _load_xy(PATTERN)
    xy = tmp_path / "manual.xy"
    with xy.open("w", encoding="utf-8", newline="\n") as fh:
        for x, y in zip(tt.tolist(), ii.tolist()):
            fh.write(f"{x:.10g} {y:.10g}\n")
    cifs = [COD_ROOT / "7" / "20" / "60" / "7206075.cif",
            COD_ROOT / "9" / "00" / "16" / "9001681.cif"]
    win_b = MainWindow()
    try:
        win_b._load_pattern_path(xy, wavelength=1.5406)
        win_b._load_cif_paths(cifs)
        rwp_manual = _rwp_after_recipe(win_b, qapp)
    finally:
        win_b.close()
        qapp.processEvents()

    assert rwp_xinm == pytest.approx(rwp_manual, rel=1e-12), (
        rwp_xinm, rwp_manual)
