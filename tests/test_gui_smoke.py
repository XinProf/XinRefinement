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
    # v1.6：列表文案改成「化学式 · 物相名称」，画布显隐仍按内部相名
    key = item.data(Qt.UserRole)
    assert key and key != item.text()
    item.setCheckState(Qt.Unchecked)
    qapp.processEvents()
    assert key not in win.canvas._visible
    assert win._result.rwp == rwp_before
    item.setCheckState(Qt.Checked)
    qapp.processEvents()
    assert key in win.canvas._visible


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
    # v1.6：键统一为 ASCII（alpha…），未勾选的分量仅为 False，不再「禁用」
    assert set(s["anatase"]) == {"a", "b", "c", "alpha", "beta", "gamma"}
    assert s["anatase"]["b"] is False and s["anatase"]["beta"] is False

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
    # v1.4 #18：B 步已落地，配方只剩 xyz 一步 skipped
    assert sum(r.status == "done" for r in records) == 7
    assert sum(r.status == "skipped" for r in records) == 1
    assert win._step_status.get("xyz") == "skipped"
    assert win.btn_run_all.isEnabled()
    assert not win.btn_cancel.isEnabled()


def test_inputs_use_rietveld_intensity_convention(win):
    """出厂配置必须用 ``integrated=True``（Rietveld 标度 S 的标准口径）。

    v1.1.0 及以前 GUI 给 ``False``（v0.1.0 峰高旧口径）：峰高口径下峰宽随
    2θ 变化会直接扭曲相对强度，实样对拍实测同配置差 3.65 个百分点。
    """
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A])
    inp = win._make_inputs()
    assert inp is not None
    assert inp.profile.integrated is True


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
    """P3.5：结果区五页（摘要/定量/晶胞/收敛/相关性），摘要含 DW 与 e.s.d.。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    # v1.6 新增「物相定量」「晶胞与微结构」两页
    assert win.result_tabs.count() == 5
    assert win.quant_table.rowCount() == len(win._phases) + 1
    assert win.cell_table.rowCount() == len(win._phases)
    labels = [win.result_table.item(r, 0).text()
              for r in range(win.result_table.rowCount())]
    assert any("Durbin-Watson" in s for s in labels)
    assert any("e.s.d." in s for s in labels)
    assert win.conv_canvas.figure.axes  # 收敛曲线已绘制
    assert win.corr_table.rowCount() >= 1


def test_p35_retranslate_tab_titles(win, qapp):
    win.switch_language("en")
    qapp.processEvents()
    # v1.6：标签页数量变了，按控件定位而非写死下标
    assert win.result_tabs.tabText(win.result_tabs.indexOf(win.result_table)) \
        == "Summary"
    assert win.result_tabs.tabText(win.result_tabs.indexOf(win.conv_canvas)) \
        == "Convergence"
    assert win.result_tabs.tabText(win.result_tabs.indexOf(win.quant_table)) \
        == "Phase quantities"
    assert win.result_table.horizontalHeaderItem(0).text() == "Metric"
    win.switch_language("zh")
    qapp.processEvents()
    assert win.result_tabs.tabText(win.result_tabs.indexOf(win.quant_table)) \
        == "物相定量"


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
    """编辑=物相参数编辑；精修=一键连跑+停止；帮助=注册码+关于。"""
    em = win._menus["menu.edit"]
    rm = win._menus["menu.refine"]
    hm = win._menus["menu.help"]
    assert em.actions() and em.actions()[0].text().startswith("物相参数编辑")
    assert [a.text() for a in rm.actions()] == ["一键连跑（默认配置）", "停止"]
    help_texts = [a.text() for a in hm.actions() if a.text()]
    assert "关于…" in help_texts
    # 正式版才有「输入注册码」；内部版（测试环境默认 release）无则为内部版
    if win._registration is not None:
        assert any("输入注册码" in t for t in help_texts)
    # 精修菜单一键连跑与面板按钮指向同一入口
    assert win.btn_run_all.isEnabled()


def test_file_menu_has_xinm_import(win):
    """v1.1.0 联合计划：文件菜单含「导入 XinMatch 物相分析」。"""
    fm = win._menus["menu.file"]
    texts = [a.text() for a in fm.actions() if a.text()]
    assert any("导入 XinMatch" in t for t in texts)
    # 保存/打开工程的文件对话框默认 .xinr（zip 容器），且兼容 .xrp
    assert win._menu_actions["menu.import_xinm"] is not None


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


# ---------------------------------------------------------------- v1.1b --
def test_axis_x_d_mode_conversion(win, qapp):
    """横轴 2θ ↔ d：Bragg 换算、反向轴、轴标签、标记条同步换算。"""
    from xinrefinement.gui.canvas import two_theta_to_d

    # Bragg 定律：Cu Kα1 下 25.28° ≈ 锐钛矿 (101) d≈3.52 Å
    d = float(two_theta_to_d(25.28, 1.5406))
    assert abs(d - 3.521) < 0.01
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    c = win.canvas
    c.set_x_mode("d")
    qapp.processEvents()
    assert c.x_mode == "d"
    x0, x1 = c.ax_main.get_xlim()
    assert x0 > x1            # d 随 2θ 递减 → 轴反向
    assert "d (Å)" in c.ax_main.get_xlabel()
    # 标记条峰位同样换算到 d（v1.6 元组带展示名，共 4 项）
    names = c.phase_names
    sticks = {k: (e, lab) for k, e, lab in c._phase_sticks}
    entry = sticks[names[0]][0]
    pos2t = entry[0][0] if isinstance(entry[0], (list, tuple)) else entry[0]
    conv = c._sticks_in_units(
        [(names[0], sticks[names[0]][0], 0, sticks[names[0]][1])])[0][1][0]
    pos_d = conv[0] if isinstance(conv, (list, tuple)) else conv
    assert abs(float(pos_d) - float(two_theta_to_d(pos2t, c.wavelength))) < 1e-9
    c.set_x_mode("2theta")
    assert "2θ" in c.ax_main.get_xlabel()


def test_axis_y_log_sqrt_modes(win, qapp):
    """纵轴 counts ↔ log ↔ √：标度、量程与轴标签。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    c = win.canvas
    c.set_y_mode("log")
    qapp.processEvents()
    assert c.ax_main.get_yscale() == "log"
    assert c.ax_main.get_ylim()[0] > 0
    assert "log" in c.ax_main.get_ylabel()
    c.set_y_mode("sqrt")
    qapp.processEvents()
    assert c.ax_main.get_yscale() == "function"
    assert "√" in c.ax_main.get_ylabel()
    c.set_y_mode("linear")
    qapp.processEvents()
    assert c.ax_main.get_yscale() == "linear"
    # 循环：linear → log → sqrt → linear
    assert c.cycle_y_mode() == "log"
    assert c.cycle_y_mode() == "sqrt"
    assert c.cycle_y_mode() == "linear"
    # 非法模式不生效
    c.set_y_mode("bogus")
    assert c.y_mode == "linear"


def test_axis_click_hit_zones(win, qapp):
    """轴区命中：纵轴标签侧/横轴标签侧命中，轴间缝隙不误触发。"""
    import types

    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    c = win.canvas
    mb = c.ax_main.get_window_extent()
    db = c.ax_diff.get_window_extent()
    ev_y = types.SimpleNamespace(x=mb.x0 - 20, y=(mb.y0 + mb.y1) / 2,
                                 inaxes=None, button=1, guiEvent=None)
    ev_x = types.SimpleNamespace(x=(mb.x0 + mb.x1) / 2, y=db.y0 - 20,
                                 inaxes=None, button=1, guiEvent=None)
    ev_gap = types.SimpleNamespace(x=(mb.x0 + mb.x1) / 2,
                                   y=(mb.y0 + db.y1) / 2,
                                   inaxes=None, button=1, guiEvent=None)
    assert c._hit_axis(ev_y) == "y"
    assert c._hit_axis(ev_x) == "x"
    assert c._hit_axis(ev_gap) is None
    # 左键循环（经完整交互路径）
    c._on_button_press(ev_y)
    assert c.y_mode == "log"
    c._on_button_press(ev_x)
    assert c.x_mode == "d"
    # 右键不直接改模式（只弹菜单，离屏下无 guiEvent 用中心兜底，安全跳过执行）
    ev_r = types.SimpleNamespace(x=mb.x0 - 20, y=(mb.y0 + mb.y1) / 2,
                                 inaxes=None, button=3, guiEvent=None)
    c._hover_axis = None
    # 不实际 exec 菜单：离屏 exec 会阻塞，只验证路径识别
    assert c._hit_axis(ev_r) == "y"




def test_toolbar_buttons_have_colored_icons(win):
    """工具栏功能按钮都有彩色图标（快捷方式入口；点选背景为 checkable
    文字按钮，v1.3 新增，不要求图标）。"""
    from xinrefinement.gui.button_icons import toolbar_icon

    expected = {"toolbar.new", "toolbar.import_pattern",
                "toolbar.import_cif", "toolbar.refine", "toolbar.report",
                "toolbar.bg_pick"}
    assert set(win._toolbar_buttons) == expected
    icon_keys = expected - {"toolbar.bg_pick"}   # 点选背景为文字按钮（无图标）
    for key, btn in win._toolbar_buttons.items():
        if key not in icon_keys:
            continue
        pm = btn.icon().pixmap(32, 32)
        assert not pm.isNull(), key
        assert pm.width() == 32, key
    # 多尺寸齐全（高 DPI 清晰度）
    icon = toolbar_icon("toolbar.refine")
    sizes = {s.width() for s in icon.availableSizes()}
    assert {16, 20, 24, 32, 48} <= sizes
    assert toolbar_icon("unknown.key") is None


# ---------------------------------------------------------------- v1.1 R-3 --
def _build_xinm(tmp_path: Path, *, anatase_cell: dict | None = None) -> Path:
    """按联合计划 §2.1 契约构造 .xinm（内嵌真实包内 CIF）。"""
    import json
    import zipfile

    cell = anatase_cell or {"a": 3.785, "b": 3.785, "c": 9.5196,
                            "alpha": 90.0, "beta": 90.0, "gamma": 90.0}
    manifest = {
        "format": "xinm", "version": 1,
        "created": "2026-11-05T12:00:00",
        "app": {"name": "XinMatch", "version": "3.4.0"},
        "pattern": {"file": "pattern/pattern.csv",
                    "source_path": "D:/data/demo.xy", "wavelength": 1.5406,
                    "anode": "Cu", "tmin": 5.0, "tmax": 90.0, "step": 0.5,
                    "metadata": {"sample": "demo"}},
        "peaks": [],
        "phases": [
            {"name": "anatase", "source": "cod", "entry_id": "96-900-8211",
             "cif_file": "cifs/anatase.cif", "structural": True, "reason": "",
             "fom": None, "scale_factor": 1.0, "two_theta_shift": 0.0,
             "weight_fraction": 0.5, "cell": cell,
             "space_group": "I41/amd", "formula": "O2 Ti",
             "mineral_name": "anatase"},
            {"name": "rutile", "source": "cod", "entry_id": "96-900-4143",
             "cif_file": "cifs/rutile.cif", "structural": True, "reason": "",
             "fom": None, "scale_factor": 1.0, "two_theta_shift": 0.0,
             "weight_fraction": 0.5,
             "cell": {"a": 4.5922, "b": 4.5922, "c": 2.9574,
                      "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
             "space_group": "P4_2/mnm", "formula": "O2 Ti",
             "mineral_name": "rutile"},
            {"name": "pdf2card", "source": "pdf2", "entry_id": "01-070-1234",
             "cif_file": None, "structural": False,
             "reason": "ICDD 条目无结构数据", "fom": None,
             "scale_factor": 1.0, "two_theta_shift": 0.0,
             "weight_fraction": None, "cell": None,
             "space_group": "P4_2/mnm", "formula": "O2 Ti",
             "mineral_name": None},
        ],
        "candidates_summary": [], "restraints": {}, "notes": "",
    }
    tt = [5.0 + 0.5 * i for i in range(171)]
    ii = [100.0 + 30.0 * (i % 7) for i in range(171)]
    out = tmp_path / "analysis.xinm"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pattern/pattern.csv",
                    "two_theta,intensity\n"
                    + "\n".join(f"{x:.10g},{y:.10g}"
                                for x, y in zip(tt, ii)))
        zf.writestr("cifs/anatase.cif", CIF_A.read_bytes())
        zf.writestr("cifs/rutile.cif", CIF_R.read_bytes())
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
    return out


def test_apply_xinm_payload_prefills_edits(win, qapp, tmp_path):
    """R-3a：谱图 + 两相 CIF 装载，PDF2 相仅参照，晶胞/空间群一致即预填。"""
    from xinrefinement.core.io.xinm_import import read_xinm

    payload = read_xinm(_build_xinm(tmp_path))
    report = win._apply_xinm_payload(payload, stem="joint")
    qapp.processEvents()
    assert report is not None
    assert report["n_points"] == 171
    assert len(win._phases) == 2
    assert len(report["structural"]) == 2
    assert [p.name for p in report["reference_only"]] == ["pdf2card"]
    # wavelength 传导（画布 d 轴换算依赖它）
    assert win._pattern.meta["wavelength"] == pytest.approx(1.5406)
    # 晶胞一致 → phase_edits 预填，且无 mismatch（空间群 :1/下划线归一化后不误报）
    assert set(win._phase_edits) == {st.name for st in win._phases}
    assert report["mismatch"] == []


def test_apply_xinm_payload_flags_cell_mismatch(win, qapp, tmp_path):
    """XinMatch 侧晶胞与 CIF 显著不符：不覆盖 CIF，列清单提示。"""
    from xinrefinement.core.io.xinm_import import read_xinm

    bad = {"a": 3.90, "b": 3.90, "c": 9.60,
           "alpha": 90.0, "beta": 90.0, "gamma": 90.0}
    payload = read_xinm(_build_xinm(tmp_path, anatase_cell=bad))
    report = win._apply_xinm_payload(payload, stem="mismatch")
    qapp.processEvents()
    assert report is not None
    names = [n for n, _ in report["mismatch"]]
    assert "anatase" in names
    # 以 CIF 为准：晶胞仍为 CIF 值
    st = next(s for s in win._phases if s.name == "anatase")
    assert abs(st.cell[0] - 3.785) < 1e-6
    assert "anatase" not in win._phase_edits


def test_restore_result_panel_from_project(tmp_path):
    """R-2a：打开工程后回填结果摘要与收敛曲线（无需重新精修）。"""
    import json
    import zipfile

    from xinrefinement.gui.project import FORMAT, load_project

    full = {
        "r_factors": {"rwp": 3.409617, "rp": 2.1, "rexp": 1.9, "chi2": 3.2},
        "fit": {"iters": 14},
        "phases": [{"name": "anatase", "weight_pct": 50.03}],
        "rwp_history": [9.0, 5.0, 3.409617],
        "diagnostics": {"dw": 1.85, "verdict": "ok",
                        "rwp_start": 9.0, "rwp_final": 3.409617},
        "esd": {"weight_esd_pct": [0.21]},
    }
    p = tmp_path / "r.xinr"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": FORMAT, "format_version": 2,
            "result": {"rwp": 3.409617}, "result_full": "result/refine.json",
            "pattern": {}, "cifs": [], "settings": {}, "phase_edits": {},
            "navigation": {}}))
        zf.writestr("result/refine.json", json.dumps(full))
    data = load_project(p)
    assert data["result_full"]["r_factors"]["rwp"] == pytest.approx(3.409617)

    from xinrefinement.gui.main_window import MainWindow

    w = MainWindow()
    w._restore_result_panel(data)
    labels = [w.result_table.item(r, 0).text()
              for r in range(w.result_table.rowCount())]
    assert "Rwp (%)" in labels
    assert any("物相含量" in s for s in labels)
    assert w.conv_canvas.figure.axes[0].lines   # 收敛曲线已绘制
    w.close()
