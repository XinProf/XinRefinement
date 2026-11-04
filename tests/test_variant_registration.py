"""双变体（release/internal）与 PolyXRD-Reg 注册机制测试。

覆盖：
- 变体判定（环境变量、默认 fail-safe=release、显示名）；
- 注册码生成/校验闭环、容错输入、篡改拒绝；
- 注册状态文件读写（校验失败按未注册，防手改伪造）；
- GUI 差异：正式版有注册标签 + 「输入注册码」菜单；内部版红字「内部评估版本」且无注册菜单。
"""
from __future__ import annotations

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from xinrefinement import build_variant  # noqa: E402
from xinrefinement import registration as reg  # noqa: E402


# ------------------------------------------------------------------ 变体 --
def test_variant_default_is_release(monkeypatch):
    monkeypatch.delenv("XINREFINEMENT_VARIANT", raising=False)
    assert build_variant.current_variant() == "release"
    assert build_variant.is_release() and not build_variant.is_internal()
    assert build_variant.variant_display_name() == "正式版"


def test_variant_env_override(monkeypatch):
    monkeypatch.setenv("XINREFINEMENT_VARIANT", "internal")
    assert build_variant.is_internal()
    assert build_variant.variant_display_name() == "内部评估版"
    assert build_variant.INTERNAL_STATUS_TEXT == "内部评估版本"
    monkeypatch.setenv("XINREFINEMENT_VARIANT", "RELEASE")   # 大小写容错
    assert build_variant.is_release()
    monkeypatch.setenv("XINREFINEMENT_VARIANT", "bogus")     # 非法值回落
    assert build_variant.is_release()


# ---------------------------------------------------------------- 注册码 --
def test_registration_code_roundtrip():
    unit = "清华大学材料学院"
    code = reg.generate_code(unit)
    assert code.startswith(reg.CODE_PREFIX + "-")
    assert reg.verify_code(code) == unit
    # 容错：去连字符、小写、无前缀、夹杂空白
    body = code.split("-", 1)[1].replace("-", "")
    assert reg.verify_code(body.lower()) == unit
    assert reg.verify_code(f" {body} ") == unit


def test_registration_code_rejects_tampering():
    code = reg.generate_code("单位A")
    body = code.split("-", 1)[1]
    chars = list(body)
    chars[0] = "B" if chars[0] != "B" else "C"
    assert reg.verify_code(reg.CODE_PREFIX + "-" + "".join(chars)) is None
    assert reg.verify_code("") is None
    assert reg.verify_code("PXRD1-XXXX") is None
    with pytest.raises(ValueError):
        reg.generate_code("")
    with pytest.raises(ValueError):
        reg.generate_code("x" * 101)


def test_registration_state_file_roundtrip(tmp_path):
    path = tmp_path / "registration.json"
    assert reg.load_state(path).registered is False
    unit = "某某大学 分析测试中心"
    state = reg.save_state(path, reg.generate_code(unit))
    assert state.registered and state.unit == unit
    assert reg.load_state(path).registered is True
    # 手改 JSON 伪造「已注册」无效
    path.write_text('{"code": "PXRD1-FAKE", "unit": "%s"}' % unit,
                    encoding="utf-8")
    assert reg.load_state(path).registered is False
    # 损坏文件按未注册处理，不抛异常
    path.write_text("{not json", encoding="utf-8")
    assert reg.load_state(path).registered is False
    with pytest.raises(ValueError):
        reg.save_state(path, "PXRD1-INVALID-CODE")


def test_registration_status_text_language(tmp_path):
    path = tmp_path / "registration.json"
    reg.set_language("zh")
    assert reg.RegistrationState(False).status_text == "未注册"
    unit = "单位B"
    reg.save_state(path, reg.generate_code(unit))
    reg.set_language("en")
    st = reg.load_state(path)
    assert st.status_text.startswith("Registered:")
    reg.set_language("ja")
    assert "登録済み" in st.status_text
    reg.set_language("zh")


def test_registration_manager_label(tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    mgr = reg.RegistrationManager("XinRefinement", tmp_path / "r.json")
    lbl = mgr.label(None)
    assert lbl.text() == "未注册"
    reg.save_state(tmp_path / "r.json", reg.generate_code("单位C"))
    mgr.refresh()
    assert lbl.text() == "已注册：单位C"
    del app


# -------------------------------------------------------------------- GUI --
def test_gui_release_has_registration(qapp):
    from xinrefinement.gui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win._registration is not None
        text = win.registration_status_text()
        assert text == "未注册" or text.startswith("已注册：")
        assert win._registration_label is not None
        actions = [a.text() for a in win._menus["menu.help"].actions()]
        assert any("输入注册码" in t for t in actions)
    finally:
        win.close()
        qapp.processEvents()


def test_gui_internal_variant(qapp, monkeypatch):
    monkeypatch.setenv("XINREFINEMENT_VARIANT", "internal")
    from xinrefinement.gui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win._registration is None
        assert win.registration_status_text() == "内部评估版本"
        assert win._registration_label.text() == "内部评估版本"
        assert "d32f2f" in win._registration_label.styleSheet()   # 红字
        actions = [a.text() for a in win._menus["menu.help"].actions()]
        assert not any("输入注册码" in t for t in actions)
        assert any("关于" in t for t in actions)                 # 关于仍在
    finally:
        win.close()
        qapp.processEvents()


def test_gui_about_shows_variant(qapp, monkeypatch):
    from xinrefinement.gui.about import AboutDialog
    from PySide6.QtWidgets import QLabel

    monkeypatch.setenv("XINREFINEMENT_VARIANT", "internal")
    dlg = AboutDialog(None)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert any("内部评估版" in t for t in texts)
    dlg.close()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
