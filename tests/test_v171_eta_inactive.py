"""v1.7 K30：``refine_eta`` 在 TCH / 各向异性路径是哑参数（修复契约）。

``forward._accumulate_peaks`` 在 (X, Y) != (0, 0) 的峰上用 ``tch_eta()``
的逐峰 η，忽略 ``ProfileParams.eta``；只有退回 Caglioti 标量分支的峰才
用它。7 个基准样全相开 Popa LB 时 100% 走 TCH，配方 profile 步却仍以
``refine_eta=True`` 精修它 —— 往 LM 向量放了一列恒零雅可比，还把
``n_params`` 多算 1（Rexp 偏小）。

修复：在 ``refine()`` 入口检测 eta 是否真的生效，无效时局部关掉该槽位。
计算谱 / Rwp / 精修参数逐位不变，只是不再为不存在的自由度付费。

覆盖：
1. ``eta_is_active``：无各向异性 → True；全相各向异性 → False；混合 → True；
2. 全相各向异性时 ``refine_eta=True`` 与 ``=False`` 的结果逐位相同
   （含 rexp，证明 ``n_params`` 已不再多算那 1 个自由度）；
3. 标量分支时 eta 仍是有效自由度（开/关结果不同，修复不能误伤）；
4. 合成谱自洽：两种路径的 ycalc 都有限且非负。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams, aniso_default)
from xinrefinement.core.refine.nonlinear import RefineConfig, eta_is_active
from xinrefinement.core.refine.solve import RefineInputs, solve

ROOT = Path(__file__).resolve().parent.parent
DATA_CIF = ROOT / "xinrefinement" / "data"
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"


def _setup(*, aniso: str = "all", refine_eta: bool = True):
    """aniso: "all" 全相 / "none" 无 / "mixed" 只给第一相。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA_CIF / "anatase.cif"),
              parse_cif(DATA_CIF / "rutile.cif")]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=True)
    if aniso != "none":
        targets = phases if aniso == "all" else phases[:1]
        prm = replace(prm, aniso={
            s.name: aniso_default(1.5406, 0.0, 0.05) for s in targets})
    cfg = RefineConfig(refine_zero=False, refine_uvw=True,
                       refine_eta=refine_eta, n_bg=3, max_iter=8,
                       tmin=5.0, tmax=90.0, bg_mode="tent")
    return pat, phases, prm, cfg


def _run(*, aniso: str = "all", refine_eta: bool = True):
    pat, phases, prm, cfg = _setup(aniso=aniso, refine_eta=refine_eta)
    return solve(RefineInputs(pattern=pat, phases=phases,
                              profile=prm, config=cfg))


def test_eta_is_active_scalar_vs_tch() -> None:
    _, phases, prm_none, _ = _setup(aniso="none")
    assert eta_is_active(phases, prm_none, 5.0, 90.0) is True

    _, phases, prm_all, _ = _setup(aniso="all")
    assert eta_is_active(phases, prm_all, 5.0, 90.0) is False

    _, phases, prm_mixed, _ = _setup(aniso="mixed")
    # 第二相仍走 Caglioti 标量分支，eta 必须保留
    assert eta_is_active(phases, prm_mixed, 5.0, 90.0) is True


def test_dead_eta_slot_is_dropped_and_rexp_matches_explicit_off() -> None:
    """修复的核心可观测差异：n_params 不再多算哑参数，rexp 与显式关闭相同。"""
    on = _run(aniso="all", refine_eta=True)
    off = _run(aniso="all", refine_eta=False)
    assert on.rwp == off.rwp
    assert on.rp == off.rp
    assert on.rexp == off.rexp          # 修复前这里会差 1 个 P
    assert on.chi2 == off.chi2
    assert np.array_equal(on.ycalc, off.ycalc)
    assert on.params.U == off.params.U
    assert on.params.V == off.params.V
    assert on.params.W == off.params.W


def test_scalar_branch_eta_remains_a_real_freedom() -> None:
    """不能把有效自由度误关：无各向异性时开关必须改变结果。"""
    on = _run(aniso="none", refine_eta=True)
    off = _run(aniso="none", refine_eta=False)
    assert on.rwp != off.rwp
    assert not np.array_equal(on.ycalc, off.ycalc)


def test_solve_result_config_keeps_user_setting() -> None:
    """局部替换不应改写 SolveResult.config（对外契约不变）。"""
    res = _run(aniso="all", refine_eta=True)
    assert res.config.refine_eta is True


def test_ycalc_finite_and_nonnegative() -> None:
    for aniso in ("none", "all"):
        res = _run(aniso=aniso)
        assert np.all(np.isfinite(res.ycalc))
        assert float(res.ycalc.min()) >= -1e-6
