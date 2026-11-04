"""精修引擎接口契约测试（T1.3 验收 · INV-3）。

只验**契约形状**（字段存在、类型、边界常量），不跑耗时精修 ——
真实数据的回归由 T1.4 的 golden 基线负责。
"""
from __future__ import annotations

import dataclasses

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig, RefineResult
from xinrefinement.core.refine.rfactors import RFactors, compute_rfactors


def test_pattern_contract() -> None:
    p = Pattern(two_theta=np.array([10.0, 10.02, 10.04]),
                intensity=np.array([1.0, 2.0, 3.0]))
    assert p.step == np.float64(0.02) or abs(p.step - 0.02) < 1e-9
    assert p.meta == {}


def test_refine_result_fields() -> None:
    """T1.4 / T3.2 / T4.1 会往这里追加字段，但既有字段一个都不许少。"""
    required = {"params", "scales", "bg", "ycalc", "rf", "success", "history",
                "phase_dropped", "restarted", "cell_scales", "iters", "po_r"}
    got = {f.name for f in dataclasses.fields(RefineResult)}
    assert required <= got, f"缺失字段: {required - got}"


def test_refine_config_fields() -> None:
    required = {"refine_zero", "refine_uvw", "refine_eta", "n_bg", "max_iter",
                "sigma", "tmin", "tmax", "bg_mode", "refine_asym",
                "refine_bfactor", "refine_cell", "backend", "refine_po"}
    got = {f.name for f in dataclasses.fields(RefineConfig)}
    assert required <= got, f"缺失字段: {required - got}"


def test_profile_params_fields() -> None:
    required = {"zero", "U", "V", "W", "eta", "anode", "ka_ratio", "po_r",
                "wavelength", "asym", "bfactor", "integrated"}
    got = {f.name for f in dataclasses.fields(ProfileParams)}
    assert required <= got, f"缺失字段: {required - got}"


def test_rfactors_math() -> None:
    """R 因子口径自检：y_calc == y_obs 时 Rwp = 0；常数偏移时公式可反算。"""
    y = np.array([100.0, 200.0, 300.0, 400.0])
    same = compute_rfactors(y, y, n_params=1)
    assert same.rwp == 0.0 and same.rp == 0.0

    off = compute_rfactors(y, y + 10.0, n_params=1)
    # 手算：w=1/y，Σw·Δ²=100·(1/100+1/200+1/300+1/400)，Σw·y²=100+200+300+400=1000
    denom = 100.0 + 200.0 + 300.0 + 400.0
    num = 100.0 * (1 / 100 + 1 / 200 + 1 / 300 + 1 / 400)
    assert off.rwp == np.float64(100 * np.sqrt(num / denom)) or \
        abs(off.rwp - 100 * np.sqrt(num / denom)) < 1e-9


def test_rbragg_not_implemented_yet() -> None:
    """T1.3 阶段 RB 仍是空位；T4.1 会填上。此处作为**提醒型**断言。"""
    rf = compute_rfactors(np.array([1.0, 2.0]), np.array([1.0, 2.0]), n_params=1)
    assert isinstance(rf, RFactors)
    assert rf.rbragg is None, "RB 已实现 —— 请把本测试改成正值断言（T4.1）"
