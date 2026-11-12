"""v1.6.4 B02 · e.s.d. 三处重复计算收敛为一次复用。

``MainWindow._esd_for`` 是唯一入口：一次 estimate_esd 要跑 4p 次全谱前向
（``core/refine/esd.py``），全在主线程，故同一精修结果只算一遍。
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xinrefinement.core.refine.solve import solve  # noqa: E402
from xinrefinement.gui.main_window import MainWindow  # noqa: E402
from xinrefinement.i18n import set_language  # noqa: E402

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


def _solve(win, *, max_iter=10):
    """用 GUI 输入跑一次真实精修（缩迭代数/背景阶数只为提速，语义同实跑）。"""
    win._load_pattern_path(PATTERN)
    win._load_cif_paths([CIF_A, CIF_R])
    inp = win._make_inputs()
    cfg = dataclasses.replace(inp.config, max_iter=max_iter, n_bg=3,
                              po_probe=False, aniso_auto=False)
    return inp, solve(dataclasses.replace(inp, config=cfg))


@pytest.fixture()
def calls(monkeypatch):
    """给 estimate_esd 挂计数器（_esd_for 是函数内 import，改模块属性即生效）。"""
    import xinrefinement.core.refine.esd as esd_mod

    hits = []
    real = esd_mod.estimate_esd

    def spy(phases, res, *args, **kwargs):
        hits.append(res)
        return real(phases, res, *args, **kwargs)

    monkeypatch.setattr(esd_mod, "estimate_esd", spy)
    return hits


def test_esd_cached_for_same_result(win, calls):
    """同一 (res, phases) 连续两次：只算一次，且返回同一对象。"""
    _inp, res = _solve(win)
    first = win._esd_for(res)
    second = win._esd_for(res)
    assert len(calls) == 1
    assert first is not None
    assert first is second


def test_esd_called_once_across_result_panels(win, calls):
    """结果面板 → 保存工程 → 结果面板（真实调用链）合计只算一次。"""
    _inp, res = _solve(win)
    win._result = res
    win._fill_results(res)
    state = win.project_state()
    win._fill_results(res)
    assert state["result_full"]["esd"] is not None
    assert len(calls) == 1
    labels = [win.result_table.item(r, 0).text()
              for r in range(win.result_table.rowCount())]
    assert sum("e.s.d." in s for s in labels) == len(res.phases)


def test_esd_failure_cached(win, monkeypatch):
    """异常路径：也只走一次，返回 None，结果面板不炸、无 e.s.d. 行。"""
    import xinrefinement.core.refine.esd as esd_mod

    _inp, res = _solve(win)
    win._result = res
    failures = []

    def boom(phases, r, *args, **kwargs):
        failures.append(r)
        raise RuntimeError("boom")

    monkeypatch.setattr(esd_mod, "estimate_esd", boom)
    assert win._esd_for(res) is None
    assert win._esd_for(res) is None
    assert len(failures) == 1
    win._fill_results(res)
    labels = [win.result_table.item(r, 0).text()
              for r in range(win.result_table.rowCount())]
    assert not any("e.s.d." in s for s in labels)
    # 原行为：这一行只在 e.s.d. 成功时才有
    assert not any("Rwp 下降" in s for s in labels)


def test_esd_cache_invalidated_by_new_result(win, calls):
    """新精修结果（新 SolveResult）必须重算。"""
    inp, res1 = _solve(win)
    win._esd_for(res1)
    assert len(calls) == 1
    res2 = solve(dataclasses.replace(
        inp, config=dataclasses.replace(inp.config, max_iter=5)))
    assert res2 is not res1
    win._esd_for(res2)          # 新结果 → 重算
    assert len(calls) == 2
    win._esd_for(res2)          # 同一新结果 → 再次命中
    assert len(calls) == 2


def test_esd_cache_invalidated_by_phase_change(win, calls):
    """物相被改动（晶胞变）→ 缓存失效，重算一次后再次命中。"""
    _inp, res = _solve(win)
    win._esd_for(res)
    assert len(calls) == 1
    st = win._phases[0]
    st.cell = tuple(v * 1.01 if i < 3 else v for i, v in enumerate(st.cell))
    win._esd_for(res)
    assert len(calls) == 2
    win._esd_for(res)
    assert len(calls) == 2


def test_new_project_clears_esd_cache(win, calls):
    """新建工程必须清空 e.s.d. 缓存：键含 id()，旧键跨工程已无意义。"""
    _inp, res = _solve(win)
    assert win._esd_for(res) is not None
    assert win._esd_cache is not None
    assert len(calls) == 1

    win.new_project()
    assert win._esd_cache is None

    again = win._esd_for(res)   # 缓存确实失效 → 对同一 res 重算一次
    assert len(calls) == 2
    # new_project 清了 _phases，空相表下 estimate_esd 抛异常 → 缓存 None
    assert again is None


def test_esd_numeric_identity(win, calls):
    """缓存值 == 直接调用值（本改造只减少重复调用，不改任何数值）。"""
    from xinrefinement.core.refine.esd import estimate_esd

    _inp, res = _solve(win)
    cached = win._esd_for(res)
    assert len(calls) == 1
    direct = estimate_esd(win._phases, res)
    assert cached is not None and direct is not None
    assert cached.labels == direct.labels
    assert cached.esd == direct.esd
    assert cached.weight_esd_pct == direct.weight_esd_pct
    assert cached.scale_esd == direct.scale_esd
    assert cached.variance_factor == direct.variance_factor
    assert cached.schur_consistency == direct.schur_consistency
