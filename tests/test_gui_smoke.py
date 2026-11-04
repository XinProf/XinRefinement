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
