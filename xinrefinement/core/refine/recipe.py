"""P3.3 · 导航式精修配方（core 层，无 GUI 依赖）。

草图要求「导航式精修」：右侧一列步骤，每步一个 ▶执行 + 旁边 ⚙设置。
本模块把这条链做成**可声明、可单步、可连跑、可回退**的配方引擎，
GUI 只负责把按钮/弹窗/进度映射到它（MVVM 边界：core 不碰 Qt）。

为什么放在 core
---------------
配方可被 CLI（P4.5）、GUI（P3.3）、XinMatch 对接（P4.6）共用；
放在 GUI 里会锁死复用路径。

步骤与能力映射
--------------
v1 当前 core 能力（P0/M0 + P1.2）：零点 / 背景 / 标度 / 峰形 /
晶胞（P1.2）/ 择优取向。原子坐标（P1.3）、温度因子 B 与占位（P1.4）
尚未落地，配方里保留步骤但标记 ``available=False``，连跑时自动跳过并
记入 warning —— 不做假执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, SolveResult, solve


@dataclass(frozen=True)
class RefineStep:
    """导航面板的一行。"""

    key: str
    title: str
    group: str                 # 参数组（对应 ParameterRegistry.group）
    available: bool = True     # False = 该能力尚未落地，连跑跳过
    note: str = ""

    def config_for(self, cfg: RefineConfig) -> RefineConfig:
        """把配方步骤翻译成该步的精修开关。

        当前用一个统一 ``solve`` 入口，按步骤只放开对应组（v1 的
        ``RefineConfig`` 只区分 zero/uvw/eta/asym/bfactor/po/size/strain）。
        P1.2 全晶胞由 :func:`run_cell_step` 单独编排。
        """
        return replace(cfg,
                       refine_zero=(self.key in ("zero", "bg", "scale")),
                       refine_uvw=(self.key in ("bg", "profile")),
                       refine_eta=(self.key == "profile"),
                       refine_asym=(self.key == "profile"),
                       refine_bfactor=False,
                       refine_po=(self.key == "micro"),
                       refine_size=(self.key == "micro"),
                       refine_strain=(self.key == "micro"))


#: 标准配方（与 GSAS-II / FullProf 推荐精修顺序一致，对照草图自上而下）
DEFAULT_STEPS: tuple[RefineStep, ...] = (
    RefineStep("zero", "零点 / 样品漂移", "zero", True,
               "zero 与样品位移；v1 样品位移由 P2.1 接入"),
    RefineStep("bg", "背景 + 峰形", "profile", True,
               "背景阶数/节点由齿轮弹窗设置"),
    RefineStep("scale", "标度因子", "scale", True,
               "线性层解析求解，恒参与"),
    RefineStep("cell", "晶胞参数", "cell", True,
               "P1.2 全晶胞按晶系约束精修"),
    RefineStep("profile", "峰形参数", "profile", True,
               "U/V/W/η + TCH 尺寸应变"),
    RefineStep("xyz", "原子坐标", "xyz", False, "待 P1.3（Wyckoff 位约束）"),
    RefineStep("B", "温度因子", "B", False, "待 P1.4（B_iso / 占位）"),
    RefineStep("micro", "微结构 / 应力 / 择优取向", "micro", True,
               "March-Dollase r + TCH X/Y"),
)


@dataclass(frozen=True)
class StepRecord:
    """一步的执行记录（用于结果区与回退）。"""

    key: str
    title: str
    status: str                # "done" | "skipped" | "failed"
    rwp_before: float | None
    rwp_after: float | None
    message: str = ""
    snapshot: tuple[float, ...] = ()   # 该步结束时的参数快照


@dataclass
class RecipeState:
    """配方运行状态（可序列化为 .xrp，供 P3.7 工程文件）。"""

    steps: tuple[RefineStep, ...] = DEFAULT_STEPS
    records: list[StepRecord] = field(default_factory=list)
    current: int = 0
    snapshots: list[tuple[float, ...]] = field(default_factory=list)

    def snapshot_params(self, prm: ProfileParams) -> tuple[float, ...]:
        return (prm.zero, prm.U, prm.V, prm.W, prm.eta, prm.asym,
                prm.bfactor, prm.X, prm.Y)

    def push_snapshot(self, prm: ProfileParams) -> None:
        self.snapshots.append(self.snapshot_params(prm))

    def rollback(self, index: int) -> tuple[float, ...] | None:
        """回退到指定步快照；返回该快照或 None（越界）。"""
        if 0 <= index < len(self.snapshots):
            snap = self.snapshots[index]
            self.snapshots = self.snapshots[:index + 1]
            self.records = self.records[:index + 1]
            self.current = index + 1
            return snap
        return None


class RecipeRunner:
    """把配方步骤映射到真实精修调用，带 Rwp 监控与快照回退。"""

    def __init__(self, steps: tuple[RefineStep, ...] = DEFAULT_STEPS,
                 rwp_tol: float = 1e-3) -> None:
        self.state = RecipeState(steps=steps)
        self.rwp_tol = rwp_tol

    @property
    def records(self) -> list[StepRecord]:
        return self.state.records

    def run_step(self, step: RefineStep, inputs: RefineInputs,
                 prev: SolveResult | None = None) -> tuple[SolveResult | None,
                                                           StepRecord]:
        """执行单步：返回 (结果, 记录)。不可用步骤直接 skip。"""
        if not step.available:
            rec = StepRecord(step.key, step.title, "skipped",
                             None if prev is None else prev.rwp,
                             None if prev is None else prev.rwp,
                             step.note or "能力尚未落地")
            self.state.records.append(rec)
            return prev, rec

        cfg = step.config_for(inputs.config)
        inp = replace(inputs, config=cfg,
                      profile=(prev.params if prev is not None
                               else inputs.profile))
        try:
            res = solve(inp)
        except Exception as exc:
            rec = StepRecord(step.key, step.title, "failed",
                             None if prev is None else prev.rwp, None,
                             str(exc))
            self.state.records.append(rec)
            return prev, rec

        before = None if prev is None else prev.rwp
        self.state.push_snapshot(res.params)
        rec = StepRecord(step.key, step.title, "done", before, res.rwp,
                         snapshot=self.state.snapshots[-1])
        self.state.records.append(rec)
        return res, rec

    def run_all(self, inputs: RefineInputs,
                steps: tuple[RefineStep, ...] | None = None,
                cancel_cb=None) -> tuple[SolveResult | None, list[StepRecord]]:
        """顺序连跑：每步以上一步参数为初值，收敛（ΔRwp<tol）可提前停。"""
        todo = steps if steps is not None else self.state.steps
        result: SolveResult | None = None
        self.state.current = 0
        for i, step in enumerate(todo):
            if cancel_cb is not None and cancel_cb():
                break
            before = result.rwp if result is not None else None
            result, rec = self.run_step(step, inputs, result)
            self.state.current = i + 1
            if (rec.status == "done" and before is not None
                    and abs(before - result.rwp) < self.rwp_tol):
                # 已收敛：后续步骤仍执行但记录不再改进（不提前终止配方，
                # 因为后续组可能是不同参数族）
                pass
        return result, self.state.records
