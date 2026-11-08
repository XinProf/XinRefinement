"""P3.3 · 后台精修线程（不阻塞 UI，可取消）。

家族 GUI 约定：精修在 QThread 中执行，进度/迭代通过 Signal 回主线程；
主线程只更新控件（Qt 禁止跨线程操作 QWidget）。

信号
----
- ``step_started(key, title)``：开始一步；
- ``step_finished(key, status, rwp, message)``：一步结束；
- ``progress(msg, pct)``：文本进度；
- ``finished_ok(result)`` / ``failed(msg)``：整体结束。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from xinrefinement.core.refine.recipe import (
    DEFAULT_STEPS,
    GUI_TIME_BUDGET_S,
    RecipeRunner,
    RefineStep,
)
from xinrefinement.core.refine.solve import RefineInputs, SolveResult


class RefineWorker(QThread):
    """按配方可选单步 / 连跑的后台精修线程。"""

    step_started = Signal(str, str)
    step_finished = Signal(str, str, object, str)
    #: v1.6：(step_key, params, phases) —— 每步结束时的参数快照。
    #: 左下的「跑码窗口」靠它打印「参数: 旧值 → 新值」；没有这份数据，
    #: 界面上只能看到 Rwp 在跳，看不到具体哪个参数动了。
    step_snapshot = Signal(str, object, object)
    progress = Signal(str, object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, inputs: RefineInputs, steps=None,
                 single_step: str | None = None, parent=None,
                 time_budget_s: float | None = None) -> None:
        super().__init__(parent)
        self._inputs = inputs
        self._steps = tuple(steps) if steps is not None else DEFAULT_STEPS
        self._single = single_step
        self._cancel = False
        # v1.5 M9b：GUI 全链墙钟预算。None = 出厂默认 45 min（micro 齿轮
        # 可改，0 = 不限）；连跑超预算时慢步自适应降迭代、可选步跳过，
        # 防 GUI 出现一次精修 >1 h（样 4 实测 44.5 min 已压线）。
        if time_budget_s is None:
            time_budget_s = GUI_TIME_BUDGET_S
        self._runner = RecipeRunner(self._steps, time_budget_s=time_budget_s)

    def cancel(self) -> None:
        """请求取消（下一步边界检查；当前步内的 LM 由 cancel_cb 逐次评估检查）。"""
        self._cancel = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancel

    @property
    def runner(self) -> RecipeRunner:
        return self._runner

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            todo = (self._steps if self._single is None
                    else tuple(s for s in self._steps if s.key == self._single))
            if not todo:
                self.failed.emit(f"未找到步骤 {self._single!r}")
                return

            result: SolveResult | None = None
            for step in todo:
                if self._cancel:
                    break
                self.step_started.emit(step.key, step.title)
                self.progress.emit(f"正在执行「{step.title}」…", None)
                result, rec = self._runner.run_step(
                    step, self._inputs, result)
                # 参数快照：配方里 cell 步会把新晶胞回写 runner.phases，
                # 所以两样都要传（只传 params 看不到晶胞变化）。
                # 先发快照再发 finished：日志里参数行应排在本步收尾行之前。
                self.step_snapshot.emit(
                    rec.key,
                    getattr(result, "params", None),
                    tuple(self._runner.phases or ()))
                self.step_finished.emit(
                    rec.key, rec.status, rec.rwp_after, rec.message)
                self.progress.emit(
                    f"「{step.title}」{rec.status}"
                    + ("" if rec.rwp_after is None
                       else f"  Rwp={rec.rwp_after:.3f}%"), None)

            if result is not None:
                self.finished_ok.emit(result)
            else:
                self.failed.emit("精修被取消或未产生结果")
        except Exception as exc:  # 线程内异常必须转成信号，不能让 QThread 静默死
            self.failed.emit(str(exc))
