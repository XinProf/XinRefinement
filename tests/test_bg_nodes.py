"""v1.5 M8d：背景节点数的界面口径（离屏，不弹窗）。

动机来自 §1.9 的全样评测：tent 背景加密（19→46 节点）在 6 个样里 5 个
改善（均值 −0.63 pt），但 QPA 最多漂 2.76 vol%，故**不改默认值**，只把
这条路做成「明确可选」。要可选就必须先修两处界面缺陷：

1. 齿轮弹窗节点数上限 30——5–120° 每 2.5° 一节点要 46 个，旧上限直接堵死；
2. 弹窗首次打开时读代码级兜底 3，用户点「确定」就把 19 默默降成 3。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import xinrefinement.gui.main_window as mw  # noqa: E402
from xinrefinement.core.refine.linear import adaptive_n_bg  # noqa: E402
from xinrefinement.gui.dialogs import BackgroundDialog  # noqa: E402
from xinrefinement.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
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


# --- 弹窗 -----------------------------------------------------------------

def test_dialog_accepts_dense_nodes(qapp):
    """46 节点（5–120° 每 2.5°）必须能填进去。"""
    dlg = BackgroundDialog({"n_bg": 46, "bg_mode": "tent"})
    assert dlg.n_terms.value() == 46
    assert dlg.settings()["n_bg"] == 46
    assert dlg.n_terms.maximum() >= 60


def test_dialog_keeps_explicit_value(qapp):
    dlg = BackgroundDialog({"n_bg": 29, "bg_mode": "tent"})
    assert dlg.settings()["n_bg"] == 29


# --- 窗口口径 -------------------------------------------------------------

def test_refine_window_priority(win):
    """micro 齿轮 > bg 齿轮 > 兜底 5–90°。"""
    assert win._refine_window() == (5.0, 90.0)
    win._settings["bg"] = {"tmin": 10.0, "tmax": 100.0}
    assert win._refine_window() == (10.0, 100.0)
    win._settings["micro"] = {"tmin": 5.0, "tmax": 120.0}
    assert win._refine_window() == (5.0, 120.0)
    win._settings["micro"] = {"tmin": 120.0, "tmax": 5.0}      # 反向 → 兜底
    assert win._refine_window() == (5.0, 90.0)


# --- 弹窗初值 -------------------------------------------------------------

def test_dialog_seeded_with_adaptive_default(win, monkeypatch):
    """首次打开背景齿轮：初值必须是自适应节点数，不是 3。"""
    win._settings["micro"] = {"tmin": 5.0, "tmax": 120.0}
    seen: dict = {}

    def fake_open(step, title, names, current=None, parent=None, **kw):
        seen["n_bg"] = None if current is None else current.get("n_bg")
        return None

    monkeypatch.setattr(mw, "open_settings", fake_open)
    win.open_step_settings("bg", "背景曲线")
    assert seen["n_bg"] == adaptive_n_bg(5.0, 120.0) == 19


def test_explicit_nodes_not_overridden(win, monkeypatch):
    """用户已显式设过节点数时，不能再被自适应值覆盖。"""
    win._settings["micro"] = {"tmin": 5.0, "tmax": 120.0}
    win._settings["bg"] = {"n_bg": 46, "bg_mode": "tent"}
    seen: dict = {}

    def fake_open(step, title, names, current=None, parent=None, **kw):
        seen["n_bg"] = current.get("n_bg")
        return None

    monkeypatch.setattr(mw, "open_settings", fake_open)
    win.open_step_settings("bg", "背景曲线")
    assert seen["n_bg"] == 46


def test_other_steps_untouched(win, monkeypatch):
    """只有 bg 步做初值灌入，别的步保持 None（走各自弹窗默认）。"""
    seen: dict = {}

    def fake_open(step, title, names, current=None, parent=None, **kw):
        seen[step] = current
        return None

    monkeypatch.setattr(mw, "open_settings", fake_open)
    win.open_step_settings("cell", "晶胞")
    assert seen["cell"] is None
