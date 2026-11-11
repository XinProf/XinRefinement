"""v1.6.2 · 停止按钮的响应粒度（步内取消）。

背景：v1.6.1 及以前，``RefineWorker.cancel()`` 只置一个标志，而这个标志
只在**步与步之间**检查 → 点「停止」要等当前步整步跑完。慢步（cell 步内部
3 次 solve、micro 步试探 + 正式 + 重解、profile 步最多 4 次 LM 重启）
在实样上是分钟级，用户体感就是「点了没反应」。

修法：把取消回调挂进 ``RefineConfig.cancel_cb``，引擎的
``_check_cancel`` 在**每次残差评估入口**检查（主 solve / 晶胞引擎 /
站点引擎三个闭包都接上）。

本文件守四件事：
1. 步内取消确实抛 ``RefineCancelled``，且停在第几次评估就停（不跑完整步）；
2. 从「请求取消」到「异常到达」的延迟在一次残差评估量级；
3. 没挂回调时行为逐位不变（正常步仍是 done）；
4. 配方层不会把取消记成「失败」（否则用户会看到假的失败告警）。
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.cell import refine_cell_full
from xinrefinement.core.refine.nonlinear import RefineCancelled, RefineConfig
from xinrefinement.core.refine.recipe import DEFAULT_STEPS, RecipeRunner
from xinrefinement.core.refine.solve import RefineInputs

ROOT = Path(__file__).resolve().parents[1]
PATTERN = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"
CIF_A = ROOT / "xinrefinement" / "data" / "anatase.cif"
CIF_R = ROOT / "xinrefinement" / "data" / "rutile.cif"
BY_KEY = {s.key: s for s in DEFAULT_STEPS}


def _inputs(cancel_cb=None, max_iter: int = 40) -> RefineInputs:
    pat = load_pattern(PATTERN)
    phases = [parse_cif(str(CIF_A)), parse_cif(str(CIF_R))]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode="Cu", integrated=False)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3,
                       tmin=5.0, tmax=90.0, max_iter=max_iter,
                       cancel_cb=cancel_cb)
    return RefineInputs(pattern=pat, phases=phases, profile=prm, config=cfg)


def test_cancel_cb_aborts_inside_step():
    """第 3 次残差评估就取消 → 立刻中断，而不是跑完整步再看标志。"""
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= 3

    with pytest.raises(RefineCancelled):
        RecipeRunner().run_step(BY_KEY["profile"], _inputs(cancel_cb=cancel))
    # 少一次都不算：说明检查点确实落在残差评估里，而不是步边界
    assert calls[0] == 3


def test_cancel_lands_within_one_residual():
    """请求取消 → 异常到达的延迟应在一次残差评估量级（远小于整步）。"""
    t0 = time.monotonic()
    requested = {"t": None}

    def cancel():
        if requested["t"] is None and time.monotonic() - t0 > 0.05:
            requested["t"] = time.monotonic()
        return requested["t"] is not None

    with pytest.raises(RefineCancelled):
        RecipeRunner().run_step(BY_KEY["profile"], _inputs(cancel_cb=cancel))
    assert requested["t"] is not None, "取消回调从未被调用（钩子没接上）"
    latency = time.monotonic() - requested["t"]
    # 一次残差评估在本机是毫秒级；给足慢机器余量仍应远小于整步（~0.8 s）
    assert latency < 0.5, f"停止延迟 {latency:.3f}s 过长，钩子可能只落在步边界"


def test_without_cancel_cb_step_stays_bitwise_same():
    """默认 ``cancel_cb=None``：步照常 done，Rwp 与基准一致（零回归守）。"""
    step = BY_KEY["profile"]
    res_none, rec_none = RecipeRunner().run_step(step, _inputs())
    res_cb, rec_cb = RecipeRunner().run_step(
        step, _inputs(cancel_cb=lambda: False))
    assert rec_none.status == "done" and rec_cb.status == "done"
    assert rec_none.rwp_after == rec_cb.rwp_after
    assert res_none.rwp == res_cb.rwp


def test_cell_engine_honours_cancel():
    """晶胞引擎是独立残差闭包，必须自己接取消钩子。"""
    # 基准用**不带回调**的配置解出来，否则 scale 步自己就会先触发取消
    plain = _inputs()
    base = RecipeRunner().run_step(BY_KEY["scale"], plain)[0]
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= 4

    cfg = replace(plain.config, cancel_cb=cancel)
    with pytest.raises(RefineCancelled):
        refine_cell_full(list(plain.phases), base.pattern, base.params, cfg)
    assert calls[0] == 4


def test_run_all_does_not_record_cancel_as_failure():
    """连跑取消：任意取消时机都不产生 status='failed' 的假记录。

    原用例用 ``time.monotonic() - t0 > 0.15`` 赌「第一步一定在 0.15 s 内
    跑完」，在负载 / 慢机器上会拿到 records == [] 而误报（QA 基线已复现）。
    这里改用残差检查点计数谓词，与墙钟完全解耦；断言的是真正的产品契约
    （取消不被记成失败、记录状态只能是 done/skipped、结果与已完成记录一致），
    而不再附加「至少完成一步」这个 recipe.py:960-963 从未承诺的前置条件。
    """
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= 3          # 第 3 次残差检查点（首步内）请求取消

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert all(r.status != "failed" for r in records), \
        [(r.key, r.status, r.message) for r in records]
    assert all(r.status in ("done", "skipped") for r in records)
    assert (res is None) == (len(records) == 0)


@pytest.mark.parametrize("cancel_at", [1, 2, 3, 10, 40, 10**9])
def test_cancel_at_any_checkpoint_keeps_contract(cancel_at):
    """覆盖：首个检查点 / 首步内 / 步间 / 链尾 / 从不取消。

    cancel_at=10**9 等价于「不取消」，用于校验全链 8 步的基线记录形态。
    """
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= cancel_at

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert all(r.status != "failed" for r in records), \
        [(r.key, r.status, r.message) for r in records]
    assert all(r.status in ("done", "skipped") for r in records)
    assert (res is None) == (len(records) == 0)


def test_cancel_preserves_completed_partial_results(monkeypatch):
    """确定性：取消发生在第 3 步内时，前 2 步的已完成结果必须保留。

    用 monkeypatch 包一层 run_step 计数「已完成步数」，谓词只认这个计数，
    因此完全不受迭代次数 / 墙钟 / 机器负载影响，也不依赖任何魔法数字。
    """
    orig = RecipeRunner.run_step
    completed = [0]

    def spy(self, step, inputs, prev=None):
        out = orig(self, step, inputs, prev)   # 取消异常会在此透传，不计数
        completed[0] += 1
        return out

    monkeypatch.setattr(RecipeRunner, "run_step", spy)

    def cancel():
        return completed[0] >= 2          # 已跑完 2 步；第 3 步首个检查点即取消

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert len(records) == 2
    assert all(r.status == "done" for r in records)
    assert res is not None
    assert all(r.status != "failed" for r in records)
