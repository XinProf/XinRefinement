"""v1.5 M8c：多型建议在 GUI 里的接线（离屏，不弹窗）。

只测「按钮出现 → 点击 → 相被替换 → 触发重跑」这条链路，不真的做精修。
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.refine.nonlinear import BISO_BOUNDS  # noqa: E402
from xinrefinement.core.refine.polymorph import DATA_DIR  # noqa: E402
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


def _beta_phase():
    """模拟用户误给的 β 方石英（同化学式，Fd-3m）。"""
    st = parse_cif(DATA_DIR / "cristobalite_alpha.cif")
    st.name = "5 Entry_96-900-8234"
    st.spacegroup = "F d -3 m"
    return st


def test_button_hidden_by_default(win):
    assert win.btn_polymorph.isHidden()
    assert win._polymorph_suggestion is None


def test_button_shows_on_hit_and_applies(win, monkeypatch):
    st = _beta_phase()
    win._phases[:] = [st]
    win._cif_paths[:] = ["/orig/5 Entry.cif"]
    res = SimpleNamespace(params=SimpleNamespace(b_iso={st.name: BISO_BOUNDS[1]}))

    win._refresh_polymorph_suggestion(res)
    assert not win.btn_polymorph.isHidden()
    assert "α" in win.btn_polymorph.text()

    ran: dict = {}
    monkeypatch.setattr(win, "run_recipe_all",
                        lambda: ran.setdefault("ran", True))
    monkeypatch.setattr(win, "_refresh_sticks", lambda: None)

    win._on_apply_polymorph()
    assert ran.get("ran") is True
    assert win._phases[0].spacegroup == "P 41 21 2"
    assert len(win._phases[0].atoms) == 12
    # 相名保持，配方/结果表/QPA 的键才不会错位
    assert win._phases[0].name == st.name
    assert win._cif_paths[0].endswith("cristobalite_alpha.cif")
    assert win.btn_polymorph.isHidden()
    assert win._polymorph_suggestion is None


def test_button_stays_hidden_without_hit(win):
    st = _beta_phase()
    win._phases[:] = [st]
    res = SimpleNamespace(params=SimpleNamespace(b_iso={st.name: 1.0}))
    win._refresh_polymorph_suggestion(res)
    assert win.btn_polymorph.isHidden()


def test_starting_new_run_clears_stale_suggestion(win, monkeypatch):
    st = _beta_phase()
    win._phases[:] = [st]
    win._refresh_polymorph_suggestion(
        SimpleNamespace(params=SimpleNamespace(b_iso={st.name: BISO_BOUNDS[1]})))
    assert not win.btn_polymorph.isHidden()
    monkeypatch.setattr(win, "_start_worker", lambda *a, **k: None)
    win.run_recipe_all()
    assert win.btn_polymorph.isHidden()
    assert win._polymorph_suggestion is None
