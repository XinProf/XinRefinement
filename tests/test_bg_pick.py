"""v1.3 · 画布点选背景锚点（MAUD 手工背景点语义）验收。

契约：
- 左键在主轴上添加锚点（强度取实测谱插值），再次点击（±0.15°）移除；
- 锚点按 2θ 排序存储、d 模式下自动换算（点击 d → 存 2θ）；
- 信号携带完整列表；主窗口回写 settings.bg 并自动切 manual 模式；
- manual 锚点经既有 bg_points 路径进引擎（引擎侧已在 v1.2.0 验收）。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from xinrefinement.gui.canvas import (  # noqa: E402
    PatternCanvas,
    d_to_two_theta,
    two_theta_to_d,
)

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    from xinrefinement.core.patterns import load_pattern

    pat = load_pattern(PATTERN)
    cv = PatternCanvas()
    cv.show_pattern(pat.two_theta, pat.intensity)
    return cv


def test_d_two_theta_roundtrip():
    tt = np.array([10.0, 30.0, 60.0, 89.0])
    d = two_theta_to_d(tt, 1.54056)
    back = d_to_two_theta(d, 1.54056)
    assert np.allclose(back, tt, atol=1e-9)


def test_pick_add_remove_toggle(canvas):
    got: list[list] = []
    canvas.bgPointsChanged.connect(lambda p: got.append(list(p)))
    canvas.set_pick_mode(True)
    assert canvas.pick_mode
    # 添加
    act = canvas.toggle_bg_pick(30.0)
    assert act == "added"
    assert len(canvas.bg_picks) == 1
    tt, y = canvas.bg_picks[0]
    assert tt == pytest.approx(30.0)
    assert y == pytest.approx(float(np.interp(
        30.0, canvas._two_theta, canvas._yobs)))
    assert got and len(got[-1]) == 1
    # 容差内再点 → 移除
    act = canvas.toggle_bg_pick(30.05)
    assert act == "removed"
    assert canvas.bg_picks == []
    assert got[-1] == []


def test_picks_sorted_by_two_theta(canvas):
    for tt in (50.0, 20.0, 35.0):
        assert canvas.toggle_bg_pick(tt) == "added"
    tts = [x for x, _y in canvas.bg_picks]
    assert tts == sorted(tts)
    assert tts == [20.0, 35.0, 50.0]


def test_pick_out_of_range_ignored(canvas):
    lo, hi = float(canvas._two_theta[0]), float(canvas._two_theta[-1])
    assert canvas.toggle_bg_pick(lo - 5.0) == "none"
    assert canvas.toggle_bg_pick(hi + 5.0) == "none"
    assert canvas.bg_picks == []


def test_clear_all_emits(canvas):
    canvas.toggle_bg_pick(25.0)
    canvas.toggle_bg_pick(45.0)
    got: list[list] = []
    canvas.bgPointsChanged.connect(lambda p: got.append(list(p)))
    canvas.clear_bg_picks()
    assert canvas.bg_picks == []
    assert got[-1] == []


def test_main_window_settings_roundtrip(qapp):
    """主窗口：锚点变化回写 settings.bg 并自动切 manual；工程恢复画布标记。"""
    from xinrefinement.gui.main_window import MainWindow

    win = MainWindow()
    try:
        # 开启点选模式（工具栏按钮路径）
        win._toggle_bg_pick_mode(True)
        assert win.canvas.pick_mode
        # 模拟画布锚点变化
        win._on_bg_picks_changed([(20.0, 123.0), (45.0, 87.5)])
        bg = win._settings["bg"]
        assert bg["bg_mode"] == "manual"
        assert bg["bg_points"] == [(20.0, 123.0), (45.0, 87.5)]
        # 恢复：set_bg_picks 灌回画布
        win.canvas.set_bg_picks(bg["bg_points"])
        assert win.canvas.bg_picks == [(20.0, 123.0), (45.0, 87.5)]
    finally:
        win.close()
