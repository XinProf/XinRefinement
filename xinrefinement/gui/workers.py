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

from dataclasses import replace

from PySide6.QtCore import QThread, Signal

from xinrefinement.core.refine.nonlinear import RefineCancelled
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
        """请求取消：**下一次残差评估**即生效（v1.6.2）。

        回调通过 ``RefineConfig.cancel_cb`` 挂在配置上，引擎的
        ``_check_cancel`` 在每次残差评估入口检查——所以停止延迟是一次
        残差评估（实测量级 10 ms），而不是「等当前步跑完」。
        步边界的检查仍然保留（没有挂上回调时的兜底）。
        """
        self._cancel = True

    def _cancel_requested(self) -> bool:
        """给引擎的取消回调（属性/方法是两回事：属性求值成 bool 不可调用）。"""
        return self._cancel

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

            # v1.6.2：取消回调必须进配置，否则「停止」只在步边界生效，
            # 用户点完要等当前步整步跑完（cell 步 3 次 solve、micro 步
            # 试探 + 正式 + 重解、profile 步最多 4 次 LM 重启 → 分钟级）。
            inputs = replace(
                self._inputs,
                config=replace(self._inputs.config,
                               cancel_cb=self._cancel_requested))

            result: SolveResult | None = None
            for step in todo:
                if self._cancel:
                    break
                self.step_started.emit(step.key, step.title)
                self.progress.emit(f"正在执行「{step.title}」…", None)
                result, rec = self._runner.run_step(step, inputs, result)
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
        except RefineCancelled:
            # 步内取消：把已经算出来的结果交回去（界面显示当前谱与 Rwp），
            # 不当作错误——否则用户会在取消后收到一个「精修失败」告警框。
            if result is not None:
                self.finished_ok.emit(result)
            else:
                self.failed.emit("精修已停止（尚未产生结果）")
        except Exception as exc:  # 线程内异常必须转成信号，不能让 QThread 静默死
            self.failed.emit(str(exc))
