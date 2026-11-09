"""v1.6.1 · GUI 细节改进测试（离屏）。

覆盖这一版按截图点名的六件事：

1. 帮助页加上版权与许可（菜单项 + 许可全文对话框 + 关于页入口）；
2. 「内部评估版本」移到状态栏并居中、字号加大一号、红色加粗；
3. 左下日志标题去掉「（跑码）」；
4. 导航工具条缩小一号并移到谱图**上方**；
5. 其下新增谱图操作行（复位 / 横纵框选 / 区域放大 / 左右平移 /
   步进缩放 / 十字竖线 + 手动峰位）；
6. 八个步骤齿轮各用一色区分。
"""
from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from xinrefinement.gui.about import (  # noqa: E402
    AboutDialog,
    LicenseDialog,
    license_path,
    license_text,
)
from xinrefinement.gui.dialogs import STEPS  # noqa: E402
from xinrefinement.gui.main_window import STEP_GEAR_COLORS, MainWindow  # noqa: E402
from xinrefinement.gui.plot_tools import TOOL_GROUPS, PlotToolBar  # noqa: E402
from xinrefinement.i18n import tr  # noqa: E402

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
    w.resize(1280, 860)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


@pytest.fixture()
def loaded(win, qapp):
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    qapp.processEvents()
    return win


def _ev(canvas, x, y, button=1):
    """构造一个 matplotlib 风格的鼠标事件（不依赖真实 GUI）。"""
    return types.SimpleNamespace(
        inaxes=canvas.ax_main, xdata=x, ydata=y, button=button,
        x=1, y=1, guiEvent=None)


# ------------------------------------------------- 4/5. 工具条布局与按钮 --- #
def test_plot_toolbar_has_nine_buttons(win):
    """谱图操作行 9 个按钮，顺序与分组符合约定。"""
    tb = win.plot_toolbar
    assert isinstance(tb, PlotToolBar)
    keys = [k for group in TOOL_GROUPS for k in group]
    assert len(keys) == 9
    assert list(tb.buttons) == keys
    for key, btn in tb.buttons.items():
        assert btn.toolTip(), key
        assert btn.iconSize().width() == 22


def test_nav_toolbar_and_plot_row_sit_above_canvas(win, qapp):
    """导航工具条 → 谱图操作行 → 画布，自上而下（原来工具条在谱图下方）。"""
    qapp.processEvents()
    nav = win._nav_toolbar
    row = win.plot_toolbar
    assert nav.y() < row.y() < win.canvas.y()
    # 且都在画布的父容器里（同一列）
    assert nav.parent() is row.parent() is win.canvas.parent()


def test_nav_toolbar_icons_shrunk_one_size(win):
    """导航工具条图标缩小一号：chip 36 → 30，iconSize 24。"""
    tb = win._nav_toolbar
    assert tb.iconSize().width() == 24
    pm = tb._actions["home"].icon().pixmap(64, 64)
    assert not pm.isNull() and pm.width() == 30


# ------------------------------------------------------- 5. 谱图操作行为 --- #
def test_reset_zoom_and_pan(loaded, qapp):
    """原始谱图 / 步进放大 / 左右平移 的视场变化。"""
    c = loaded.canvas
    full = c.ax_main.get_xlim()
    c.zoom_scale(0.5)
    qapp.processEvents()
    span_full = abs(full[1] - full[0])
    span_zoom = abs(c.ax_main.get_xlim()[1] - c.ax_main.get_xlim()[0])
    assert span_zoom == pytest.approx(span_full * 0.5, rel=1e-6)
    # 缩小回原样
    c.zoom_scale(2.0)
    span_back = abs(c.ax_main.get_xlim()[1] - c.ax_main.get_xlim()[0])
    assert span_back == pytest.approx(span_full, rel=1e-6)
    # 右移 → 视场中心变大；左移 → 变小
    c.reset_view()
    centre0 = sum(c.ax_main.get_xlim()) / 2
    c.pan_x(0.25)
    assert sum(c.ax_main.get_xlim()) / 2 > centre0
    c.pan_x(-0.25)
    assert sum(c.ax_main.get_xlim()) / 2 == pytest.approx(centre0, abs=1e-6)
    # 复位：横轴回到全量
    c.reset_view()
    assert c.ax_main.get_xlim() == pytest.approx(full, rel=1e-9)


def test_band_zoom_x_y_and_rect(loaded, qapp):
    """三种框选：只改横轴 / 只改纵轴 / 两者都改。"""
    c = loaded.canvas
    c.reset_view()
    x0, x1 = c.ax_main.get_xlim()
    y0, y1 = c.ax_main.get_ylim()

    c.set_plot_tool("zoom_x")
    c._tool_press(_ev(c, x0 + 0.3 * (x1 - x0), y0 + 0.1 * (y1 - y0)))
    assert c._band is not None                    # 拖拽中出现橡皮筋
    c._on_button_release(_ev(c, x0 + 0.6 * (x1 - x0), y0 + 0.2 * (y1 - y0)))
    assert c._band is None                        # 松手后收掉
    nx0, nx1 = c.ax_main.get_xlim()
    assert nx1 - nx0 == pytest.approx(0.3 * (x1 - x0), rel=1e-6)
    # 横轴变了 → 纵轴自动贴合该区间（不空屏）
    assert c.ax_main.get_ylim()[1] <= y1

    c.reset_view()
    y0, y1 = c.ax_main.get_ylim()
    c.set_plot_tool("zoom_y")
    c._tool_press(_ev(c, x0 + 0.4 * (x1 - x0), y0 + 0.4 * (y1 - y0)))
    c._on_button_release(_ev(c, x0 + 0.5 * (x1 - x0), y0 + 0.8 * (y1 - y0)))
    ny0, ny1 = c.ax_main.get_ylim()
    assert ny1 - ny0 == pytest.approx(0.4 * (y1 - y0), rel=1e-6)
    assert c.ax_main.get_xlim() == pytest.approx((x0, x1), rel=1e-9)

    c.reset_view()
    c.set_plot_tool("zoom_rect")
    x0, x1 = c.ax_main.get_xlim()
    y0, y1 = c.ax_main.get_ylim()
    c._tool_press(_ev(c, x0 + 0.2 * (x1 - x0), y0 + 0.2 * (y1 - y0)))
    c._on_button_release(_ev(c, x0 + 0.7 * (x1 - x0), y0 + 0.7 * (y1 - y0)))
    assert abs(c.ax_main.get_xlim()[1] - c.ax_main.get_xlim()[0]) \
        == pytest.approx(0.5 * (x1 - x0), rel=1e-6)
    assert abs(c.ax_main.get_ylim()[1] - c.ax_main.get_ylim()[0]) \
        == pytest.approx(0.5 * (y1 - y0), rel=1e-6)


def test_crosshair_readout_and_disappears_when_off(loaded, qapp):
    """十字竖线：跟随鼠标、报角度与强度；取消选中即移除。"""
    c = loaded.canvas
    seen: list[str] = []
    c.cursorInfo.connect(seen.append)
    c.set_plot_tool("crosshair")
    c._on_motion(_ev(c, 25.3, 3000.0))
    assert c._cursor_line is not None
    assert c._cursor_line.get_xdata()[0] == pytest.approx(25.3)
    assert seen and "25.3" in seen[-1] and "I =" in seen[-1]
    # 移动后竖线跟着走
    c._on_motion(_ev(c, 30.0, 1200.0))
    assert c._cursor_line.get_xdata()[0] == pytest.approx(30.0)
    # 取消工具 → 竖线消失（手动峰位保留）
    c.set_plot_tool(None)
    assert c._cursor_line is None and c._cursor_text is None


def test_manual_peak_add_and_remove(loaded, qapp):
    """右键添加手动峰位；落在同一位置再右键即删除；标注随重绘保留。"""
    c = loaded.canvas
    got: list[list] = []
    c.manualPeaksChanged.connect(lambda peaks: got.append(list(peaks)))
    c.set_plot_tool("crosshair")
    assert c.toggle_manual_peak(26.5) == "added"
    assert c.manual_peaks == [26.5]
    assert len(c._peak_artists) >= 1
    assert got[-1] == [26.5]
    # 换视场（重绘）后标注仍在
    c.zoom_scale(0.8)
    assert c.manual_peaks == [26.5]
    assert c._peak_artists
    # 同位置再点 → 删除
    assert c.toggle_manual_peak(26.51) == "removed"
    assert c.manual_peaks == []
    # 右键事件路径也生效
    c._tool_press(_ev(c, 41.2, 500.0, button=3))
    assert c.manual_peaks == [41.2]


def test_manual_peaks_cleared_with_pattern(qapp):
    """新建工程（clear）后手动峰位不残留。"""
    w = MainWindow()
    w._load_pattern_path(PATTERN)
    qapp.processEvents()
    w.canvas.toggle_manual_peak(20.0)
    assert w.canvas.manual_peaks
    w.canvas.clear()
    assert w.canvas.manual_peaks == []
    w.close()


# --------------------------------------------------- 2. 内部评估版标识 --- #
def test_internal_build_label_centered_bold_bigger(qapp, monkeypatch):
    """内部版：状态栏标签居中、字号比默认大一号、红色加粗、常驻不闪。"""
    monkeypatch.setenv("XINREFINEMENT_VARIANT", "internal")
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    try:
        labels = [lb for lb in w.statusBar().findChildren(QLabel)
                  if lb.objectName() == "internalBuildLabel"]
        assert len(labels) == 1
        lb = labels[0]
        assert lb.text() == "内部评估版本"
        assert lb.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert lb.font().bold()
        assert lb.font().pointSizeF() > QApplication.font().pointSizeF()
        assert "#d32f2f" in lb.styleSheet()
        # permanent widget：showMessage 时不会消失
        w.statusBar().showMessage("临时提示")
        qapp.processEvents()
        assert lb.isVisible()
    finally:
        w.close()
        qapp.processEvents()


# --------------------------------------------------------- 3. 日志标题 --- #
def test_log_panel_title_without_paoma(win):
    """左下标题就是「精修日志」，不再挂「（跑码）」。"""
    text = win._labels["panel.log"].text()
    assert text == tr("panel.log")
    assert "跑码" not in text


# ------------------------------------------------------- 6. 齿轮配色 --- #
def test_gear_buttons_have_distinct_colors(win):
    """八个齿轮颜色各不相同（按步骤定位），且仍是 32px 方按钮。"""
    gears = win._gear_buttons
    assert len(gears) == len(STEPS) == 8
    colors = [STEP_GEAR_COLORS[step] for step, _t, _c in STEPS]
    assert len(set(colors)) == 8
    sheets = [g.styleSheet() for g in gears.values()]
    assert len(set(sheets)) == 8
    for step, btn in gears.items():
        assert STEP_GEAR_COLORS[step].lower() in btn.styleSheet().lower()
        assert btn.width() == 32
        assert btn.toolTip()


# ------------------------------------------------- 1. 版权与许可 --- #
def test_help_menu_has_license_entry(win):
    hm = win._menus["menu.help"]
    texts = [a.text() for a in hm.actions() if a.text()]
    assert tr("license.menu") in texts
    assert tr("menu.about") in texts
    # 「版权与许可」排在「关于」之前
    assert texts.index(tr("license.menu")) < texts.index(tr("menu.about"))


def test_license_dialog_shows_full_text(win):
    """许可对话框读到的是磁盘上的全文，不是代码里的摘要。"""
    dlg = LicenseDialog(win)
    text = dlg.view.toPlainText()
    assert len(text) > 400
    assert "PolyXRD Team" in text
    assert ("学术许可" in text) or ("Academic License" in text)
    assert dlg.windowTitle() == tr("license.title")
    assert dlg.view.isReadOnly()


def test_license_path_resolves_from_repo(win):
    p = license_path("zh")
    assert p is not None and p.is_file()
    assert license_path("en") is not None


def test_about_dialog_has_license_button(win):
    dlg = AboutDialog(win)
    assert dlg.btn_license.text() == tr("license.view")
    # 关于页仍保留版权与双许可摘要
    texts = [lb.text() for lb in dlg.findChildren(QLabel)]
    assert any("©2026" in t for t in texts)
    assert any("许可" in t for t in texts)
