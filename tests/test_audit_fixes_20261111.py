"""2026-11-11 审计修复（F01–F06）验收用例。

依据
----
- ``docs/audit-20261111-architecture.md`` 第 3 节（F01–F06 精确改动点）
- ``docs/audit-20261111-qa-baseline.md`` 第 9.3 节（QA 独立风险复核与
  可直接粘贴的 pytest 验收用例）

范围
----
全部用例只覆盖旁路 / 元数据 / 显示 / 序列化 / 报告字段 / 入口配置，
不触碰优化器、峰形、权重、配方默认值、参数打包顺序或任何残差 / 前向函数。
golden 数值主链由 ``tests/test_golden_b.py::test_golden_5050_bit_identical``
单独守护，本文件不重复断言数值。
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import xinrefinement.api as api  # noqa: E402
import xinrefinement.core.refine.solve as solve_mod  # noqa: E402
from xinrefinement.cli.refine import main as cli_main  # noqa: E402
from xinrefinement.core.profile.cif import parse_cif  # noqa: E402
from xinrefinement.core.profile.forward import (  # noqa: E402
    ProfileParams,
    compute_phase_profile,
)
from xinrefinement.core.profile.naming import phase_label  # noqa: E402
from xinrefinement.core.refine.cell import structure_with_cell  # noqa: E402
from xinrefinement.core.refine.nonlinear import (  # noqa: E402
    RefineConfig,
    _pack,
    _unpack,
)
from xinrefinement.gui.dialogs import STEPS  # noqa: E402
from xinrefinement.gui.main_window import MainWindow  # noqa: E402
from xinrefinement.gui.project import (  # noqa: E402
    FORMAT,
    FORMAT_VERSION,
    load_project,
    save_project,
)
from xinrefinement.i18n import (  # noqa: E402
    LANGUAGES,
    TRANSLATIONS,
    set_language,
    tr,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"
ANATASE = DATA_CIF / "anatase.cif"
RUTILE = DATA_CIF / "rutile.cif"
PATTERN = VIRTUAL_B / "v50_wide.xy"
CIF_A = ANATASE
CIF_R = RUTILE


def _common(tmp_path: Path, out_name: str) -> list[str]:
    """与 ``tests/test_cli.py::_common`` 同口径；此处自带以保持独立可运行。"""
    return [
        str(VIRTUAL_B / "v50_wide.xy"),
        str(DATA_CIF / "anatase.cif"),
        str(DATA_CIF / "rutile.cif"),
        "-o", str(tmp_path / out_name),
        "--peak-height",
        "--n-bg", "3",
    ]


# --------------------------------------------------------------------------- #
# GUI fixtures（与 tests/test_i18n_project.py 同写法：离屏、切语言后复位）
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# F01 · name_mineral 元数据搬运
# --------------------------------------------------------------------------- #
def test_structure_with_cell_preserves_name_mineral():
    """structure_with_cell 后矿物名与展示口径都不退化。"""
    st = parse_cif(ANATASE)
    assert st.name_mineral == "Anatase"
    out = structure_with_cell(st, st.cell)
    assert out.name_mineral == "Anatase"
    assert phase_label(out, "label") == "Anatase"      # 修复前退化为 "TiO2"


def test_name_mineral_is_display_only():
    """F01 的「不改数值」护栏：只改 name_mineral 不影响计算谱。"""
    st = parse_cif(ANATASE)
    a = structure_with_cell(st, st.cell)
    a.name_mineral = "Anatase"
    b = structure_with_cell(st, st.cell)
    b.name_mineral = None
    grid = np.arange(5.0, 40.0, 0.05)
    prm = ProfileParams()
    ya = compute_phase_profile(a, grid, prm, 5.0, 40.0)
    yb = compute_phase_profile(b, grid, prm, 5.0, 40.0)
    assert np.array_equal(ya, yb)


# --------------------------------------------------------------------------- #
# F02 · legacy _unpack 补 size_strain
# --------------------------------------------------------------------------- #
def test_legacy_unpack_preserves_size_strain():
    """生产 refine() 走 _unpack_reg；本用例只守兼容路径不丢字段。"""
    base = ProfileParams(anode="Cu", size_strain={"foo": (0.1, 0.2)})
    cfg = RefineConfig()                     # refine_size_strain 默认 False
    x = _pack(base, cfg, 1)
    prm, _ = _unpack(x, base, cfg, 1)
    assert prm.size_strain == {"foo": (0.1, 0.2)}     # 修复前为 None


# --------------------------------------------------------------------------- #
# F03 · api.report() 与 api.refine() 的 RefineConfig 对齐
# --------------------------------------------------------------------------- #
def test_report_and_refine_share_refine_po(monkeypatch):
    """_solve_raw 的 RefineConfig 必须带上 request.refine_po（opt-in 路径）。"""
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R),
                            refine_po=True)
    seen, sentinel = {}, object()

    def fake_solve(inp):
        seen["refine_po"] = inp.config.refine_po
        return sentinel

    monkeypatch.setattr(solve_mod, "solve", fake_solve)
    assert api._solve_raw(req) is sentinel
    assert seen["refine_po"] is True        # 修复前为 False


def test_default_refine_po_is_zero_regression(monkeypatch):
    """默认 refine_po=False 路径逐位不变（含 _solve_raw 的配置）。"""
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R))
    assert req.refine_po is False
    seen, sentinel = {}, object()

    def fake_solve(inp):
        seen["refine_po"] = inp.config.refine_po
        return sentinel

    monkeypatch.setattr(solve_mod, "solve", fake_solve)
    assert api._solve_raw(req) is sentinel
    assert seen["refine_po"] is False       # 默认路径配置未变


# --------------------------------------------------------------------------- #
# F04 · .xinr 谱图序列化 float64 全精度
# --------------------------------------------------------------------------- #
def test_xinr_pattern_roundtrip_is_bit_exact(tmp_path):
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)       # 含 >10 位有效数字的值
    xy = tmp_path / "demo.xy"
    xy.write_text("\n".join(f"{x:.17g} {y:.17g}" for x, y in zip(tt, ii)),
                  encoding="utf-8")
    cif = tmp_path / "a.cif"
    cif.write_text("data_a\n_cell_length_a 3.785\n", encoding="utf-8")
    state = {"language": "zh", "pattern": str(xy), "cifs": [str(cif)],
             "settings": {}, "phase_edits": {}, "result": None,
             "navigation": {}}
    out = tmp_path / "proj.xinr"
    save_project(state, out, embed=True)
    got = np.loadtxt(load_project(out)["pattern"])
    assert np.array_equal(got[:, 0], tt)
    assert np.array_equal(got[:, 1], ii)


def test_old_10g_xinr_still_readable(tmp_path):
    """F04 的向后兼容护栏：手工构造旧格式 .10g 内嵌谱仍可读。"""
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)
    csv_text = "two_theta,intensity\n" + "\n".join(
        f"{x:.10g},{y:.10g}" for x, y in zip(tt, ii))
    p = tmp_path / "old.xinr"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": FORMAT, "format_version": FORMAT_VERSION,
            "pattern": {"member": "pattern/pattern.csv"}}))
        zf.writestr("pattern/pattern.csv", csv_text)
    got = np.loadtxt(load_project(p)["pattern"])
    assert got.shape == (171, 2)
    assert got[:, 0] == pytest.approx(tt, rel=1e-9)


# --------------------------------------------------------------------------- #
# F05 · CLI 报告两处小修
# --------------------------------------------------------------------------- #
def test_cli_out_creates_parent_dir(tmp_path):
    """-o 指向不存在的多级目录时自动建父目录，不再抛 FileNotFoundError。"""
    out = tmp_path / "nested" / "deep" / "report.json"
    assert cli_main(
        ["refine", *_common(tmp_path, "nested/deep/report.json")]) == 0
    assert out.is_file()


def test_to_report_harmonic_fields_present(tmp_path):
    """球谐织构报告补齐 model / degree / coeffs，且保留 axis / grid 键。"""
    out = tmp_path / "h.json"
    argv = _common(tmp_path, "h.json") + [
        "--texture", "anatase=0,0,1",
        "--texture-model", "harmonic", "--texture-degree", "4",
        "--max-iter", "2"]
    assert cli_main(argv) == 0
    tex = json.loads(out.read_text(encoding="utf-8"))["parameters"]["texture"]
    assert tex["anatase"]["model"] == "harmonic"
    assert tex["anatase"]["degree"] == 4
    assert len(tex["anatase"]["coeffs"]) > 0
    # 现有 grid 型用例依赖的两个字段仍保留
    assert "axis" in tex["anatase"] and "grid" in tex["anatase"]


# --------------------------------------------------------------------------- #
# F06 · 步骤按钮文本改走 tr(f"step.{key}")
# --------------------------------------------------------------------------- #
def test_step_finished_button_follows_current_language(win, qapp):
    """切到 en 后触发 step_finished，按钮不得退回中文。"""
    win.switch_language("en")
    qapp.processEvents()
    win._on_step_finished("cell", "done", 3.4, "")
    qapp.processEvents()
    btn_text = win._step_buttons["cell"].text()
    assert tr("step.cell", "en") in btn_text        # "Cell parameters"
    assert "晶胞参数" not in btn_text               # 修复前会出现


def test_all_step_keys_have_three_languages():
    """8 个 step.* 键在 zh / en / ja 三语都齐全。"""
    keys = [s[0] for s in STEPS]
    assert len(keys) == 8
    for lang in LANGUAGES:
        for k in keys:
            assert f"step.{k}" in TRANSLATIONS[lang], (lang, k)
