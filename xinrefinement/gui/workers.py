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
    RecipeRunner,
    RefineStep,
)
from xinrefinement.core.refine.solve import RefineInputs, SolveResult


class RefineWorker(QThread):
    """按配方可选单步 / 连跑的后台精修线程。"""

    step_started = Signal(str, str)
    step_finished = Signal(str, str, object, str)
    progress = Signal(str, object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, inputs: RefineInputs, steps=None,
                 single_step: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._inputs = inputs
        self._steps = tuple(steps) if steps is not None else DEFAULT_STEPS
        self._single = single_step
        self._cancel = False
        self._runner = RecipeRunner(self._steps)

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
