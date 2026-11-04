"""P3.1/P3.2 · GUI 离屏冒烟测试（不弹窗、不抢焦点）。

覆盖：主窗口构建 / 导航步骤 / 导入谱图与 CIF / 执行精修 /
结果表 / 背景曲线重建 / 相开关即时重绘 / 齿轮弹窗设置回读 / 报告导出。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from xinrefinement.gui.dialogs import (  # noqa: E402
    STEPS,
    BackgroundDialog,
    CellDialog,
    GenericDialog,
)
from xinrefinement.gui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def win(qapp):
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


def test_main_window_skeleton(win):
    """三区骨架 + 菜单 + 8 个导航步骤（每行 ▶ + ⚙）。"""
    assert win.windowTitle().startswith("XinRefinement")
    assert len(win._step_buttons) == len(STEPS) == 8
    assert win.canvas is not None
    assert win.result_table.columnCount() == 2
    assert win.menuBar().actions()


def test_import_and_refine_end_to_end(win, qapp):
    """导入谱图 + 两个 CIF → 精修 → 结果与图谱显示（真实引擎，非假数据）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    assert win._pattern is not None and win._pattern.two_theta.size > 100
    assert len(win._phases) == 2
    assert win.phase_list.count() == 2
    assert len(win.canvas.phase_names) == 2

    win.run_refine()
    qapp.processEvents()
    res = win._result
    assert res is not None
    assert res.rwp < 10.0
    assert win.canvas.has_fit
    assert win.result_table.rowCount() >= 5
    labels = [win.result_table.item(r, 0).text()
              for r in range(win.result_table.rowCount())]
    assert "Rwp (%)" in labels
    assert any("物相含量" in s for s in labels)


def test_phase_toggle_redraws_without_refine(win, qapp):
    """相开关即时重绘（不重新精修）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    rwp_before = win._result.rwp
    item = win.phase_list.item(0)
    item.setCheckState(Qt.Unchecked)
    qapp.processEvents()
    assert item.text() not in win.canvas._visible
    assert win._result.rwp == rwp_before
    item.setCheckState(Qt.Checked)
    qapp.processEvents()
    assert item.text() in win.canvas._visible


def test_step_settings_dialogs(win, qapp):
    """齿轮弹窗：背景（函数/阶数）、晶胞（多物相分别设置）、通用组。"""
    bg = BackgroundDialog({"bg_mode": "tent", "n_bg": 5,
                           "bg_points": [(20.0, 300.0)]}, win)
    bg.mode.setCurrentIndex(0)
    assert bg.settings()["bg_mode"] == "cheb"
    assert bg.settings()["n_bg"] == 5

    cell = CellDialog(["anatase", "rutile"], {}, win)
    s = cell.settings()
    assert set(s) == {"anatase", "rutile"}
    assert s["anatase"]["a"] is True and s["rutile"]["c"] is True
    # b/α/β/γ 在 P1.2 前禁用，settings 中仍保留键但不参与精修
    assert "α" in s["anatase"]

    gen = GenericDialog("profile", "峰形参数", {}, win)
    assert "U" in gen.settings()


def test_open_step_settings_updates_state(win, monkeypatch):
    """主窗口齿轮按钮把设置写回 _settings（monkeypatch 避免模态阻塞）。"""
    monkeypatch.setattr("xinrefinement.gui.main_window.open_settings",
                        lambda *a, **k: {"n_bg": 7, "bg_mode": "tent"})
    win.open_step_settings("bg", "背景 + 峰形")
    assert win._settings["bg"]["n_bg"] == 7
    # 该设置应传导到下一次精修的 RefineConfig
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    assert win._result.config.n_bg == 7
    assert win._result.config.bg_mode == "tent"


def test_new_project_clears(win, qapp):
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A])
    win.new_project()
    qapp.processEvents()
    assert win._pattern is None and win._phases == []
    assert win.result_table.rowCount() == 0
    assert not win.canvas.has_fit


def test_recipe_all_runs_in_background(win, qapp):
    """一键连跑：后台 QThread 按配方执行，逐步记录状态并产出结果。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_recipe_all()
    assert win._worker is not None and win._worker.isRunning()
    assert win.btn_cancel.isEnabled()
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    assert win._result is not None and win._result.rwp < 10.0
    assert win.canvas.has_fit
    records = win._worker.runner.records
    assert len(records) == 8
    assert sum(r.status == "done" for r in records) == 6
    assert sum(r.status == "skipped" for r in records) == 2
    assert win._step_status.get("xyz") == "skipped"
    assert win.btn_run_all.isEnabled()
    assert not win.btn_cancel.isEnabled()


def test_single_step_via_recipe(win, qapp):
    """导航单步按钮：只执行该步（后台线程），不跑全部。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_step("zero")
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    records = win._worker.runner.records
    assert len(records) == 1 and records[0].key == "zero"
    assert win._result is not None


def test_cancel_stops_recipe(win, qapp):
    """停止按钮：请求取消后线程能收尾，不残留运行中的 QThread。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_recipe_all()
    win.cancel_refine()
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    assert win._worker.is_cancelled
    assert not win._worker.isRunning()


def test_p35_result_tabs_and_diagnostics(win, qapp):
    """P3.5：结果区三页（摘要/收敛曲线/相关性），摘要含 DW 与含量 e.s.d.。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    assert win.result_tabs.count() == 3
    labels = [win.result_table.item(r, 0).text()
              for r in range(win.result_table.rowCount())]
    assert any("Durbin-Watson" in s for s in labels)
    assert any("e.s.d." in s for s in labels)
    assert win.conv_canvas.figure.axes  # 收敛曲线已绘制
    assert win.corr_table.rowCount() >= 1


def test_p35_retranslate_tab_titles(win, qapp):
    win.switch_language("en")
    qapp.processEvents()
    assert win.result_tabs.tabText(0) == "Summary"
    assert win.result_tabs.tabText(1) == "Convergence"
    assert win.result_table.horizontalHeaderItem(0).text() == "Metric"
    win.switch_language("zh")
    qapp.processEvents()


def test_p41_report_export_via_core(win, qapp, tmp_path):
    """P4.1：报告三件套可由 GUI 结果直接导出（含 e.s.d. 段）。"""
    from xinrefinement.core.report import export_report
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    paths = export_report(win._result, tmp_path, stem="gui")
    assert all(Path(p).exists() for p in paths.values())
    assert "Durbin-Watson" in Path(paths["html"]).read_text(encoding="utf-8")


# ------------------------------------------------------------------ v1.1 --
def test_asset_loader_finds_brand_resources():
    """logo/splash 从项目 assets/ 解析（源码模式），打包走包内副本。"""
    from xinrefinement.gui.assets import app_icon, asset_path, load_pixmap

    for name in ("splash.png", "logo.png", "icons/logo_256.png",
                 "logo_transparent.png"):
        p = asset_path(name)
        assert p is not None and p.is_file(), name
    assert not load_pixmap("splash.png").isNull()
    assert app_icon() is not None


def test_maud_style_phase_tick_strips(win, qapp):
    """每相一条标记条：轴数=可见相数，残差面板高度比小于主谱。"""
    from xinrefinement.gui.canvas import normalize_sticks

    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    qapp.processEvents()
    # 单谱模式（未精修）也已画标记条：主轴 + 2 条相条 + 残差占位
    assert len(win.canvas.ax_ticks) == 2
    assert win.canvas.ax_diff is not None
    # 相对强度归一化：棒高最大值 = 1
    entries = [(20.0, 10.0), (25.0, 5.0), (30.0, 2.5)]
    pos, rel = normalize_sticks(entries)
    assert pos.size == 3 and rel.max() == 1.0 and rel[0] == 1.0
    # 关闭一相 → 标记条只剩一条
    win.phase_list.item(0).setCheckState(Qt.Unchecked)
    qapp.processEvents()
    assert len(win.canvas.ax_ticks) == 1
    win.phase_list.item(0).setCheckState(Qt.Checked)
    qapp.processEvents()


def test_refine_result_uses_intensity_sticks(win, qapp):
    """精修后标记条仍按相对强度显示（相条数与相数一致）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    assert win.canvas.has_fit
    assert len(win.canvas.ax_ticks) == len(win._phases) == 2
    # 每相标记条应是独立着色的轴（相名已写入左侧文本）
    texts = [t for ax in win.canvas.ax_ticks
             for t in ax.texts]
    assert len(texts) == 2


def test_menus_edit_refine_help(win):
    """编辑=物相参数编辑；精修=一键连跑+停止；帮助=关于。"""
    em = win._menus["menu.edit"]
    rm = win._menus["menu.refine"]
    hm = win._menus["menu.help"]
    assert em.actions() and em.actions()[0].text().startswith("物相参数编辑")
    assert [a.text() for a in rm.actions()] == ["一键连跑（默认配置）", "停止"]
    assert hm.actions() and hm.actions()[0].text().startswith("关于")
    # 精修菜单一键连跑与面板按钮指向同一入口
    assert win.btn_run_all.isEnabled()


def test_phase_edit_dialog_roundtrip(win):
    """物相编辑对话框：晶胞/择优取向/对称性设置读取与写回。"""
    from xinrefinement.gui.dialogs import PhaseEditDialog

    win._load_cif_paths([CIF_A, CIF_R])
    dlg = PhaseEditDialog(win._phases, {}, win)
    got = dlg.settings()
    assert set(got) == {"anatase", "rutile"}
    an = got["anatase"]
    assert len(an["cell"]) == 6 and an["cell"][0] > 0
    assert an["po"] is None and an["spacegroup"] is not None
    # 既往设置回读
    saved = {"anatase": {"cell": list(an["cell"]), "po": (0, 0, 1, 0.85),
                         "spacegroup": an["spacegroup"],
                         "point_group": "4/mmm", "laue_group": "4/mmm"}}
    dlg2 = PhaseEditDialog(win._phases, saved, win)
    got2 = dlg2.settings()
    assert got2["anatase"]["po"] == (0, 0, 1, 0.85)
    assert got2["anatase"]["point_group"] == "4/mmm"


def test_nav_toolbar_colorized_icons(win):
    """导航工具栏图标已按品牌色替换（8 个动作全部非空位图）。"""
    from PySide6.QtGui import QPixmap

    from xinrefinement.gui.toolbar_icons import TOOL_COLORS

    tb = win._nav_toolbar
    for callback in TOOL_COLORS:
        act = tb._actions.get(callback)
        assert act is not None, callback
        pm = act.icon().pixmap(36, 36)
        assert not pm.isNull(), callback
        assert pm.width() == 36
    # 关键动作可点击状态与原生语义不变
    assert tb._actions["zoom"].isCheckable()
    assert tb._actions["pan"].isCheckable()


def test_open_phase_editor_applies_edits(win, monkeypatch):
    """主窗口入口：晶胞写回 struct.cell，PO 传导到精修输入。"""
    # exec 返回 Accepted，避免离屏环境真弹模态循环挂死
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        "xinrefinement.gui.main_window.PhaseEditDialog.settings",
        lambda self: {self._structs[0].name:
                      {"cell": [3.7892, 3.7892, 9.5139, 90.0, 90.0, 90.0],
                       "po": (0, 0, 1, 0.9),
                       "spacegroup": "I41/amd", "point_group": "4/mmm",
                       "laue_group": "4/mmm"}})
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.open_phase_editor()
    st = win._phases[0]
    assert st.cell[0] == 3.7892 and st.cell[2] == 9.5139
    assert win._phase_po[st.name] == (0, 0, 1, 0.9)
    inputs = win._make_inputs()
    assert inputs.profile.po_r == {st.name: (0, 0, 1, 0.9)}
    # 标记条已按新晶胞/PO 重算（无异常即达意）
    assert len(win.canvas.phase_names) == 2
