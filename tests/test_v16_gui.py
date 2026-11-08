"""v1.6 · GUI 改造测试（离屏，不弹窗、不抢焦点）。

覆盖用户逐条点名的五项界面要求：

1. 左上物相列表显示「化学式 · 物相名称」，不再是 CIF 文件名；
2. 左下 MAUD 式跑码窗口（滚动打印正在精修的参数）；
3. 谱图下方标记条标签随显示口径切换（右键可选）；
4. 每个导航步骤点 ▶ 先弹「本步精修什么」说明窗，内容同步写入跑码窗口；
5. 右下新增「物相定量」「晶胞与微结构」两页，参数按多行多列铺开。

另外守住两条语义红线：``CellDialog`` 的勾选**真正**传进引擎
（``RefineConfig.cell_axes``），且默认（未设置过）时行为与 v1.5 逐位一致。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QPlainTextEdit,
    QScrollArea,
)

from xinrefinement.core.profile.cif import CifStructure  # noqa: E402
from xinrefinement.core.profile.naming import (  # noqa: E402
    DEFAULT_PHASE_LABEL_MODE,
    PHASE_LABEL_MODES,
)
from xinrefinement.gui.dialogs import (  # noqa: E402
    STEPS,
    CellDialog,
    PhaseEditDialog,
    StepDescribeDialog,
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


@pytest.fixture()
def loaded(win, qapp):
    """导入谱图 + 锐钛矿/金红石两相并精修一次（后续断言都基于真实结果）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_refine()
    qapp.processEvents()
    assert win._result is not None
    return win


def _cell_of(name: str) -> CifStructure:
    """按包内 CIF 构造裸结构（只用于晶系判定的单元测试）。"""
    if name == "cubic":
        return CifStructure("cub", (4.0, 4.0, 4.0, 90.0, 90.0, 90.0), [])
    if name == "monoclinic":
        return CifStructure("mono", (5.0, 6.0, 7.0, 90.0, 105.0, 90.0), [])
    return CifStructure("tri", (5.0, 6.0, 7.0, 77.0, 84.0, 69.0), [])


# ------------------------------------------------------- 1. 跑码窗口 --- #
def test_log_panel_replaces_placeholder(win):
    """左下是只读滚动文本（不是占位列表），能追加、能清空、不无限涨内存。"""
    lv = win.log_view
    assert isinstance(lv, QPlainTextEdit)
    assert lv.isReadOnly()
    assert lv.lineWrapMode() == QPlainTextEdit.NoWrap
    assert lv.maximumBlockCount() == 4000
    assert lv.placeholderText()

    win.log_line("=== 开始「零点 / 样品漂移」===")
    win.log_line("  zero: 0 → 0.0123")
    assert lv.toPlainText().splitlines() == [
        "=== 开始「零点 / 样品漂移」===", "  zero: 0 → 0.0123"]
    win.clear_log()
    assert lv.toPlainText() == ""


def test_param_diff_prints_only_real_changes(win):
    """参数差异行按相对 1e-9 过滤：浮点抖动不刷屏，真变化一定打出来。"""
    assert win._log_diff({}, {"a": 1.0}) == 0        # 无前值 → 不打印
    n = win._log_diff({"zero": 0.0, "TiO2.a": 3.78500},
                      {"zero": 1e-15, "TiO2.a": 3.78420})
    assert n == 1
    text = win.log_view.toPlainText()
    assert "TiO2.a" in text and "3.785" in text and "3.7842" in text
    assert "→" in text
    assert "zero" not in text


def test_state_of_flattens_cell_per_phase(loaded):
    """快照把晶胞按相展开成 ``化学式.轴``，重名多型带物相名区分。"""
    state = loaded._state_of(loaded._result.params, loaded._phases)
    assert {"zero", "U", "V", "W", "eta"} <= set(state)
    keys = [k for k in state if k.endswith(".a")]
    assert len(keys) == 2
    assert "TiO2.a" in state                      # 锐钛矿
    assert any(k.startswith("Ti0.992O2") for k in keys)   # 金红石（占位配方）
    # 人为造重名（两个 TiO2 多型）：必须补物相名，否则日志里分不清是哪相在动
    loaded._phases[1].formula = loaded._phases[0].formula
    labels = loaded._disp_unique()
    assert labels == {"anatase": "TiO2 · Anatase", "rutile": "TiO2 · Rutile"}
    flat = loaded._state_of(None, loaded._phases)
    assert "TiO2 · Anatase.a" in flat and "TiO2 · Rutile.a" in flat


def test_run_step_writes_log_begin_diff_done(win, qapp):
    """单步精修后跑码窗口有「开始 / 参数变化 / 收尾 Rwp」三类行。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.run_step("zero")
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    text = win.log_view.toPlainText()
    title = next(s[1] for s in STEPS if s[0] == "zero")
    assert f"开始「{title}」" in text
    assert "zero:" in text and "→" in text
    assert f"「{title}」done" in text


# --------------------------------------------- 2. 物相显示口径（左上）-- #
def test_default_mode_is_formula_with_mineral_hint(win):
    """左上默认「化学式 · 物相名称」；内部键仍是 CIF 名，不用于显示。"""
    assert DEFAULT_PHASE_LABEL_MODE == "formula"
    assert win._disp_mode == "formula"
    win._load_cif_paths([CIF_A, CIF_R])
    texts = [win.phase_list.item(i).text()
             for i in range(win.phase_list.count())]
    assert texts[0].startswith("TiO2 · ")
    assert all("anatase.cif" not in t for t in texts)
    # 显隐/配色按内部相名（CIF 名）索引
    assert win.phase_list.item(0).data(Qt.UserRole) == "anatase"


def test_display_mode_switches_list_and_sticks(loaded, qapp):
    """三种口径切换：列表文案、标记条标签、菜单勾选同步更新。"""
    for mode in PHASE_LABEL_MODES:
        loaded.set_display_mode(mode)
        qapp.processEvents()
        assert loaded.canvas.label_mode == mode
        labels = [lab for _k, _e, lab in loaded.canvas._phase_sticks]
        assert labels and all(labels)
        assert loaded._disp_actions[mode].isChecked()
        assert not any(loaded._disp_actions[m].isChecked()
                       for m in PHASE_LABEL_MODES if m != mode)
    # 化学式口径下不应出现 CIF 文件名
    loaded.set_display_mode("formula")
    labels = [lab for _k, _e, lab in loaded.canvas._phase_sticks]
    assert all("anatase" not in lab.lower() for lab in labels)
    # 物相名称口径取自 `_chemical_name_mineral`
    loaded.set_display_mode("label")
    labels = [lab for _k, _e, lab in loaded.canvas._phase_sticks]
    assert any("Anatase" == lab for lab in labels)


def test_display_mode_repaints_result_tables(loaded, qapp):
    """切换口径后两张表首列跟着变（不用重新精修）。"""
    from xinrefinement.core.profile.naming import phase_label

    loaded.set_display_mode("label")
    qapp.processEvents()
    mineral = phase_label(loaded._phases[0], "label")
    assert loaded.quant_table.item(0, 0).text() == mineral
    assert loaded.cell_table.item(0, 0).text() == mineral


# ------------------------------------------- 3. 步骤说明窗（右上导航）-- #
def test_step_rows_cover_all_eight_steps(loaded):
    """八步都有「修什么 + 当前值」清单，且都是两列字符串。"""
    for key, title, _group in STEPS:
        rows = loaded._step_rows(key)
        assert rows, key
        for name, val in rows:
            assert isinstance(name, str) and name
            assert isinstance(val, str)
    assert len(STEPS) == 8


def test_step_rows_cell_reflects_selection(loaded, qapp):
    """晶胞步的清单按勾选变化：全放开 vs 只勾 a。"""
    allopen = dict(loaded._step_rows("cell"))
    assert any("a、c" in v for v in allopen.values())
    loaded._settings["cell"] = {loaded._phases[0].name: {"a": True}}
    qapp.processEvents()
    rows = dict(loaded._step_rows("cell"))
    key = next(k for k in rows if "Anatase" in k or "TiO2" in k)
    assert rows[key] == "a"


def test_step_describe_dialog_matches_rows(win):
    """说明窗把清单逐条摊成日志行；空清单给兜底说明，不造假数据。"""
    rows = [("零点 zero (°)", "0.0123"), ("峰形基底", "tanθ (FWHM²)")]
    dlg = StepDescribeDialog("零点 / 样品漂移", "样品位移与零点同时拟合。",
                             rows, win)
    assert dlg.table.rowCount() == len(rows)
    assert dlg.table.columnCount() == 2
    lines = dlg.describe_lines()
    assert len(lines) == 2
    assert "零点 zero (°)" in lines[0] and "0.0123" in lines[0]
    assert "tanθ" in lines[1]
    # 标题不被「设置 · 」前缀占用
    assert dlg.windowTitle().startswith("步骤说明")

    empty = StepDescribeDialog("背景 + 峰形", "", [], win)
    assert empty.table.rowCount() == 1
    assert empty.describe_lines()


def test_describe_step_writes_log_then_refines(win, qapp, monkeypatch):
    """点 ▶ 的完整链路：弹窗确认 → 说明写入日志 → 启动该步精修。"""
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win.describe_step("zero")
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    text = win.log_view.toPlainText()
    title = next(s[1] for s in STEPS if s[0] == "zero")
    # 弹窗内容与日志逐条对应
    assert f"开始「{title}」" in text
    assert "本步精修的参数" in text
    assert "零点 zero (°)" in text
    # 起始行只出现一次（弹窗已写过就不重复）
    assert text.count(f"开始「{title}」") == 1
    assert win._result is not None


# ------------------------------------------- 4. 定量 / 晶胞两页（右下）-- #
def test_quant_tab_rows_columns_and_total(loaded):
    """定量页：显示名 / wt% / e.s.d. / Z / V，末行合计归一到 100。"""
    qt = loaded.quant_table
    assert qt.columnCount() == 5
    assert qt.rowCount() == len(loaded._result.phases) + 1
    total = sum(float(qt.item(i, 1).text())
                for i in range(qt.rowCount() - 1))
    assert total == pytest.approx(100.0, abs=0.01)
    last = qt.item(qt.rowCount() - 1, 0).text()
    assert last and qt.item(qt.rowCount() - 1, 1).text() == f"{total:.3f}"
    # 首列不是 CIF 文件名
    assert all("anatase" not in (qt.item(i, 0).text() or "").lower()
               for i in range(qt.rowCount() - 1))


def test_cell_tab_is_multi_column(loaded):
    """晶胞页铺开成 11 列：a b c α β γ / V / D / ε / 精修分量。"""
    ct = loaded.cell_table
    assert ct.columnCount() == 11
    assert ct.rowCount() == len(loaded._result.phases)
    headers = [ct.horizontalHeaderItem(c).text() for c in range(11)]
    for need in ("a", "b", "c", "α", "β", "γ"):
        assert any(h.startswith(need) for h in headers), need
    assert headers[-1] not in ("", None)
    # 数值与结果一致（不是占位）
    ph = loaded._result.phases[0]
    assert float(ct.item(0, 2).text()) == pytest.approx(ph.cell[0], abs=1e-5)
    assert float(ct.item(0, 8).text()) == pytest.approx(ph.volume, abs=1e-3)
    # 四方相：精修分量列只列自由轴
    assert ct.item(0, 1).text() == "a、c"


# --------------------------------------- 5. 晶胞弹窗铺开 + 勾选真生效 -- #
def test_cell_dialog_grid_per_phase_and_gating(win):
    """每相一个分组框、内部 3×2；非自由轴置灰并说明原因。"""
    win._load_cif_paths([CIF_A])
    dlg = CellDialog([win._phases[0].name], {}, win, structs=win._phases)
    box = dlg._boxes
    assert len(box) == 6
    # 锐钛矿四方：只有 a / c 是自由度
    assert box[("anatase", "a")].isEnabled()
    assert box[("anatase", "c")].isEnabled()
    for key in ("b", "alpha", "beta", "gamma"):
        cb = box[("anatase", key)]
        assert not cb.isEnabled(), key
        assert cb.toolTip()          # 置灰必须有原因说明
    s = dlg.settings()
    assert s["anatase"]["a"] is True and s["anatase"]["c"] is True
    assert s["anatase"]["b"] is False


def test_cell_dialog_cubic_only_a(win):
    """立方晶系只放开 a；b/c/角分量置灰（勾了也没意义）。"""
    cub = _cell_of("cubic")
    dlg = CellDialog([cub.name], {}, win, structs=[cub])
    assert dlg._boxes[("cub", "a")].isEnabled()
    for key in ("b", "c", "alpha", "beta", "gamma"):
        assert not dlg._boxes[("cub", key)].isEnabled(), key
    s = dlg.settings()
    assert s["cub"]["a"] is True
    assert s["cub"]["c"] is False


def test_cell_dialog_keys_are_internal_phase_names(win):
    """设置字典的键必须是内部相名：显示名只进标题，不参与查表。"""
    from PySide6.QtWidgets import QGroupBox

    win._load_cif_paths([CIF_A, CIF_R])
    labels = win._disp_labels()
    dlg = CellDialog(list(labels.values()), {}, win, structs=win._phases)
    assert set(dlg.settings()) == {s.name for s in win._phases}
    # 分组框标题用显示名（化学式 · 物相名称）
    titles = [g.title() for g in dlg.findChildren(QGroupBox)]
    assert any(labels[s.name] in t for s in win._phases for t in titles)


def test_phase_edit_dialog_two_columns_and_scroll(win):
    """编辑→物相参数编辑：铺开成两列并加滚动区，不再单列挤成一长条。"""
    from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox

    win._load_cif_paths([CIF_A, CIF_R])
    dlg = PhaseEditDialog(win._phases, {}, win)
    assert dlg.minimumWidth() >= 880
    assert dlg.findChildren(QScrollArea), "缺滚动区，多相时底部按钮会被挤掉"
    grids = dlg.findChildren(QGridLayout)
    assert any(g.count() >= 6 for g in grids), "设置项未铺成两列"
    assert len(dlg.findChildren(QGroupBox)) >= 6
    # combo 用显示名而不是 CIF 文件名
    labels = win._disp_labels()
    texts = [c.currentText() for c in dlg.findChildren(QComboBox)]
    assert any(labels[win._phases[0].name] in t for t in texts)


def test_cell_axes_map_default_is_none(win):
    """没在弹窗里设置过 → None（引擎按晶系全放开，v1.5 行为不变）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    assert win._cell_axes_map() is None
    inp = win._make_inputs()
    assert inp is not None and inp.config.cell_axes is None


def test_cell_axes_map_reaches_refine_config(win):
    """勾选收敛后逐相传入 RefineConfig.cell_axes（含空集：明确不想修）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win._settings["cell"] = {"anatase": {"a": True},
                             "rutile": {"a": False, "c": False}}
    got = win._cell_axes_map()
    assert got == {"anatase": ("a",), "rutile": ()}
    inp = win._make_inputs()
    assert inp.config.cell_axes == got


def test_cell_step_honours_selected_axes(win, qapp):
    """只勾 a 时 c 一个比特都不动（v1.5 那排勾选是装饰性的，v1.6 改了）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    before = [list(st.cell) for st in win._phases]
    win._settings["cell"] = {st.name: {"a": True} for st in win._phases}
    win.run_step("cell")
    assert win.wait_for_worker(60000) is True
    qapp.processEvents()
    res = win._result
    assert res is not None
    moved = []
    for i, ph in enumerate(res.phases):
        assert ph.cell[2] == pytest.approx(before[i][2], abs=1e-9)
        moved.append(abs(ph.cell[0] - before[i][0]))
    assert max(moved) > 1e-6, "勾了 a 却没动，说明勾选没接进引擎"
    # 该步描述只报 1 个自由度（不是按晶系全放的 2）
    msg = win._worker.runner.records[0].message
    assert "1 参" in msg
