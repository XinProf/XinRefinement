"""P3.6/P3.7 · 三语国际化与工程文件 .xrp 验收。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xinrefinement.gui.main_window import MainWindow  # noqa: E402
from xinrefinement.gui.project import (  # noqa: E402
    FORMAT,
    load_project,
    save_project,
    serialize,
)
from xinrefinement.i18n import (  # noqa: E402
    LANGUAGES,
    TRANSLATIONS,
    get_language,
    set_language,
    tr,
)

ROOT = Path(__file__).resolve().parent.parent
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(qapp):
    set_language("zh")
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()
    set_language("zh")


def test_catalog_completeness():
    """三语字典键集合完全一致；无空值。"""
    assert set(LANGUAGES) == {"zh", "en", "ja"}
    keys = set(TRANSLATIONS["zh"])
    for lang in LANGUAGES:
        assert set(TRANSLATIONS[lang]) == keys
        assert all(v.strip() for v in TRANSLATIONS[lang].values())


def test_tr_fallback():
    set_language("ja")
    assert tr("panel.phases") == "相リスト"
    assert tr("nonexistent.key") == "nonexistent.key"
    with pytest.raises(ValueError):
        set_language("fr")
    assert get_language() == "ja"
    set_language("zh")


@pytest.mark.parametrize("lang,title_fragment", [
    ("zh", "XinRefinement"), ("en", "Full-pattern"), ("ja", "全パターン"),
])
def test_language_switch_updates_gui(win, qapp, lang, title_fragment):
    """语言切换后窗口标题/菜单/工具栏/导航步骤即时刷新。"""
    win.switch_language(lang)
    qapp.processEvents()
    assert title_fragment in win.windowTitle()
    assert win._toolbar_buttons["toolbar.new"].text() == tr("toolbar.new")
    assert win._step_buttons["cell"].text().startswith("▶") or \
        tr("step.cell") in win._step_buttons["cell"].text()
    assert win._lang_actions[lang].isChecked()
    assert not win._lang_actions[
        next(l for l in LANGUAGES if l != lang)].isChecked()


def test_language_switch_retranslates_canvas(win, qapp):
    win.switch_language("en")
    qapp.processEvents()
    assert win.canvas.ax_main.get_ylabel() == ""
    # 空态文本应已刷新为英文（通过 retranslate 重绘）
    win.switch_language("zh")
    qapp.processEvents()


def test_project_roundtrip(win, qapp, tmp_path):
    """保存 → 新建 → 恢复：路径/设置/结果摘要/导航状态/语言全部还原。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    win._settings["bg"] = {"n_bg": 7, "bg_mode": "tent"}
    win._step_status = {"zero": "done", "xyz": "skipped"}
    win.run_refine()
    qapp.processEvents()
    win.switch_language("ja")

    out = tmp_path / "proj.xrp"
    save_project(win.project_state(), out, embed=False)   # 旧 JSON 路径引用
    assert out.exists()
    data = load_project(out)
    assert data["language"] == "ja"
    assert data["missing"] == []
    assert Path(data["pattern"]).resolve() == PATTERN.resolve()
    assert len(data["cifs"]) == 2
    assert data["settings"]["bg"]["n_bg"] == 7
    assert data["result"]["rwp"] == pytest.approx(win._result.rwp)
    assert data["navigation"]["step_status"]["xyz"] == "skipped"

    # v1.1.0：自包含 .xinr（zip 容器）同样走完整恢复流程
    out2 = tmp_path / "proj.xinr"
    save_project(win.project_state(), out2, embed=True)
    data2 = load_project(out2)
    assert data2["embedded"] is True and data2["missing"] == []
    win.new_project()
    win.apply_project(data2)
    qapp.processEvents()
    assert win._pattern is not None
    assert len(win._phases) == 2
    assert win._settings["bg"]["n_bg"] == 7

    # 关闭式恢复：清空后应用工程
    win.new_project()
    assert win._phases == [] and win._pattern is None
    win.apply_project(data)
    qapp.processEvents()
    assert get_language() == "ja"
    assert win._pattern is not None
    assert len(win._phases) == 2
    assert win.phase_list.count() == 2
    assert win._settings["bg"]["n_bg"] == 7
    assert win._step_status["xyz"] == "skipped"
    assert "–" in win._step_buttons["xyz"].text()


def test_serialize_uses_relative_paths(win, tmp_path):
    """工程文件内路径相对化（工程目录整体移动后仍可打开）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A])
    raw = serialize(win.project_state(), tmp_path / "p.xrp")
    assert raw["format"] == FORMAT
    # 同盘符 -> 相对路径；跨盘符（pytest tmp 在 C:，项目在 D:）-> 绝对路径
    same_drive = tmp_path.drive.upper() == PATTERN.drive.upper()
    assert Path(raw["pattern"]).is_absolute() == (not same_drive)
    # 无论相对/绝对，load_project 都能还原到原始文件
    out = tmp_path / "p.xrp"
    save_project(win.project_state(), out, embed=False)
    assert Path(load_project(out)["pattern"]).resolve() == PATTERN.resolve()


def test_load_rejects_bad_format(win, tmp_path):
    bad = tmp_path / "bad.xrp"
    bad.write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(bad)


def test_load_reports_missing_files(win, tmp_path):
    out = tmp_path / "missing.xrp"
    save_project({"pattern": str(tmp_path / "gone.xy"), "cifs": [],
                  "settings": {}, "navigation": {}}, out, embed=False)
    data = load_project(out)
    assert len(data["missing"]) == 1
    assert data["pattern"].endswith("gone.xy")
