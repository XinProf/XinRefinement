"""v1.5 M7：LM 数值参数（λ 初值 / 雅可比步长）的暴露与接线。

MAUD 的 ``Marquardt LS`` 用 λ=0.01、导数步长 1e-4、每轮 5 次迭代；我们
历史默认 λ=1e-3（步长已是 1e-4）。这里只做两件事：

1. **默认值一个字节都不许变** —— λ=1e-3 / 步长 1e-4 必须与不传参逐位相同
   （黄金基线 3.409617019598457 与全部历史结果都挂在它上面）；
2. λ / 步长可以从 ``RefineConfig`` 一路传到 ``lm_minimize``，供 A/B 实验。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.refine import lm as lm_mod
from xinrefinement.core.refine import optimizers
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.lm import _jacobian, lm_minimize


def _quadratic(x0=(3.0, -2.0, 0.5)):
    """病态但良定的二次型：f(x) = Σ w_i·(x_i − t_i)²。"""
    w = np.array([1.0, 10.0, 100.0])
    t = np.array([1.0, 0.5, -1.0])

    def residual(x):
        return np.sqrt(w) * (np.asarray(x, float) - t)
    return residual, t


# --- 1. 默认值 = 历史行为（逐位） ---------------------------------------

def test_default_is_bit_identical():
    f, _t = _quadratic()
    a = lm_minimize(f, np.array([3.0, -2.0, 0.5]), max_iter=40)
    b = lm_minimize(f, np.array([3.0, -2.0, 0.5]), max_iter=40,
                    lambda0=1e-3, step=1e-4)
    assert np.array_equal(a.x, b.x)
    assert a.cost == b.cost
    assert a.n_iter == b.n_iter


def test_jacobian_default_step_unchanged():
    def f(x):
        return np.array([np.sin(x[0]), x[0] * x[1]])
    x = np.array([0.7, 1.3])
    np.testing.assert_array_equal(_jacobian(f, x), _jacobian(f, x, 1e-4))


# --- 2. λ 可调且语义正确 -------------------------------------------------

def test_lambda0_reaches_same_minimum():
    """λ 只影响路径，不该影响能否到极小。"""
    f, t = _quadratic()
    for lam in (1e-6, 1e-3, 1e-2, 1e-1):
        r = lm_minimize(f, np.array([3.0, -2.0, 0.5]), max_iter=80,
                        lambda0=lam)
        assert r.success
        np.testing.assert_allclose(r.x, t, atol=1e-3)


def test_large_lambda_takes_smaller_steps():
    """同一初值下 λ 越大，第一次接受的步长越小（保守性可测）。"""
    f, _t = _quadratic()
    small = lm_minimize(f, np.array([3.0, -2.0, 0.5]), max_iter=1,
                        lambda0=1e-6)
    big = lm_minimize(f, np.array([3.0, -2.0, 0.5]), max_iter=1,
                      lambda0=1e-1)
    assert big.cost >= small.cost


# --- 3. 步长可调 ---------------------------------------------------------

@pytest.mark.parametrize("step", [1e-2, 1e-4, 1e-6])
def test_step_keeps_jacobian_accurate(step):
    """线性函数的数值雅可比与解析值一致（步长不影响正确性）。"""
    A = np.array([[1.0, 2.0], [3.0, -1.0], [0.5, 0.0]])

    def f(x):
        return A @ np.asarray(x, float)
    J = _jacobian(f, np.array([1.0, 1.0]), step)
    np.testing.assert_allclose(J, A, atol=1e-6)


# --- 4. 接线：optimizers / RefineConfig ---------------------------------

def test_run_lm_forwards_params(monkeypatch):
    seen: dict = {}

    def fake(residual_fn, x0, *, bounds=None, max_iter=60, ftol=1e-8,
             xtol=1e-8, lambda0=1e-3, step=1e-4):
        seen.update(lambda0=lambda0, step=step)
        return lm_mod.LMResult(np.asarray(x0, float), True, 0, 0.0, "ok")

    monkeypatch.setattr(lm_mod, "lm_minimize", fake)
    f, _t = _quadratic()
    optimizers.minimize(f, np.zeros(3), (np.full(3, -10.0), np.full(3, 10.0)),
                        method="lm", max_iter=10, lambda0=0.01, step=1e-5)
    assert seen == {"lambda0": 0.01, "step": 1e-5}


def test_config_defaults_are_historical():
    cfg = RefineConfig()
    assert cfg.lm_lambda0 == 1e-3
    assert cfg.lm_step == 1e-4


def test_config_reaches_optimizer(monkeypatch):
    """RefineConfig 的 λ/步长必须真的传到 _optimize（否则是死字段）。"""
    from pathlib import Path

    from xinrefinement.core.patterns import load_pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import ProfileParams
    from xinrefinement.core.refine import nonlinear as nl
    from xinrefinement.core.refine.solve import RefineInputs, solve

    root = Path(__file__).resolve().parent.parent
    pat = load_pattern(root / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    phases = [parse_cif(root / "xinrefinement" / "data" / "anatase.cif")]

    seen: list[dict] = []
    real = nl._optimize

    def spy(residual, x0, bounds, method="lm", max_iter=40, **kw):
        seen.append(dict(kw))
        return real(residual, x0, bounds, method=method, max_iter=max_iter,
                    **kw)

    monkeypatch.setattr(nl, "_optimize", spy)
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=6,
                       bg_mode="tent", max_iter=5, tmin=5.0, tmax=90.0,
                       lm_lambda0=0.01, lm_step=1e-5)
    solve(RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg))
    assert seen, "未调用优化器"
    assert seen[0]["lambda0"] == 0.01
    assert seen[0]["step"] == 1e-5


# --- 5. CLI 接线 --------------------------------------------------------

def test_cli_flags_default_off_and_map_to_config():
    """`--lm-lambda/--lm-step` 默认等于历史值，显式传入要落到 RefineConfig。"""
    from pathlib import Path

    from xinrefinement.cli.refine import _build_inputs, build_parser

    root = Path(__file__).resolve().parent.parent
    xy = str(root / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    cif = str(root / "xinrefinement" / "data" / "anatase.cif")

    p = build_parser()
    args = p.parse_args(["refine", xy, cif])
    assert args.lm_lambda == 1e-3 and args.lm_step == 1e-4

    args2 = p.parse_args(["refine", xy, cif,
                          "--lm-lambda", "0.01", "--lm-step", "1e-5"])
    assert args2.lm_lambda == 0.01 and args2.lm_step == 1e-5

    # 不跑精修，只验映射（否则是死字段）
    inputs = _build_inputs(args2)
    assert inputs.config.lm_lambda0 == 0.01
    assert inputs.config.lm_step == 1e-5
    # 默认路径同样逐位落到历史值
    assert _build_inputs(args).config.lm_lambda0 == 1e-3
