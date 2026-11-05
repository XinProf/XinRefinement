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

cell 步的特殊地位（v1.2 修正）
------------------------------
``RefineConfig.refine_cell`` 只放开每相 (fa, fc) 两个缩放，覆盖不了三斜/
单斜/正交；真正的全晶胞精修是独立引擎
:func:`xinrefinement.core.refine.cell.refine_cell_full`（按晶系放自由分量）。
因此 cell 步**不走** ``config_for`` 的开关翻译，而是由
:meth:`RecipeRunner._run_cell` 编排「solve → 精修晶胞 → 再 solve」，
并把新晶胞回写进后续步骤共用的相列表。

历史缺陷（v1.1.0 及以前）：``config_for`` 从不设 ``refine_cell=True``，
注释里提到的 ``run_cell_step`` 在整个仓库不存在 ——
cell 步 status 显示 ``done`` 但 Rwp 前后**逐位相同**，等于假装执行。
实样对拍中样品 1 的配方末值因此停在 33.74%（同配置修复后 25.92%，
其中 cell 步本身贡献 36.29% → 26.57%）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.cell import refine_cell_full, structure_with_cell
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

        ``cell`` 步**刻意**保持 ``refine_cell=False``：这一步由
        :meth:`RecipeRunner._run_cell` 调独立的全晶胞引擎
        （``refine_cell_full``）编排，若这里再打开 ``refine_cell`` 会让
        ``solve`` 顺带做一遍 (fa, fc) 缩放，两套机制抢同一组自由度。
        """
        return replace(cfg,
                       refine_zero=(self.key in ("zero", "bg", "scale")),
                       refine_uvw=(self.key in ("bg", "profile")),
                       refine_eta=(self.key == "profile"),
                       refine_asym=(self.key == "profile"),
                       refine_bfactor=False,
                       refine_cell=False,
                       refine_po=(self.key == "micro"),
                       refine_size=(self.key == "micro"),
                       refine_strain=(self.key == "micro"),
                       # v1.3 #14：织构只在 micro 步精修，且必须由调用方
                       # 显式配置（cfg.refine_texture）——配方不自动开。
                       # 其它步仍然**施加** T(χ)（prm.texture 一直在），
                       # 只是不把这 19 维放进 LM 向量。
                       refine_texture=(self.key == "micro"
                                       and cfg.refine_texture),
                       # v1.3 #15：各向异性同样只在 micro 步精修，且需
                       # 调用方显式配置（cfg.refine_aniso）。
                       refine_aniso=(self.key == "micro" and cfg.refine_aniso))
        # v1.3 评审：refine_microabs **不**在此开启。μ·r 与每相 scale 数学
        # 简并（Brindley 因子是每相常数标量，被线性层自由 scale 完全吸收），
        # 单谱精修不可辨识且 LM 会数值漂移到边界；μ·r 应由化学成分计算
        # （core.absorption / GUI「自动计算」）或用户实测给出。


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
        #: 当前相列表。cell 步精修后会把新晶胞回写到这里，后续步骤
        #: （profile/micro）必须看到改过的晶胞，否则整条链又退化成
        #: 「晶胞精修对最终结果无贡献」。
        self._phases: list[CifStructure] | None = None

    @property
    def records(self) -> list[StepRecord]:
        return self.state.records

    @property
    def phases(self) -> list[CifStructure] | None:
        """当前相列表（含 cell 步精修后的晶胞）；连跑结束后供 GUI 回写。"""
        return self._phases

    def reset(self) -> None:
        """清空运行状态与相列表（同一 runner 复用于下一次精修时调用）。"""
        self.state = RecipeState(steps=self.state.steps)
        self._phases = None

    def _phases_for(self, inputs: RefineInputs) -> list[CifStructure]:
        """首次调用时把输入的相列表接管进来（之后 cell 步会改写它）。"""
        if self._phases is None:
            self._phases = list(inputs.phases)
        return self._phases

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

        phases = self._phases_for(inputs)
        cfg = step.config_for(inputs.config)
        if step.key == "cell" and phases:
            return self._run_cell(step, inputs, prev, phases, cfg)

        inp = replace(inputs, config=cfg, phases=phases,
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

    def _run_cell(self, step: RefineStep, inputs: RefineInputs,
                  prev: SolveResult | None, phases: list[CifStructure],
                  cfg: RefineConfig) -> tuple[SolveResult | None, StepRecord]:
        """晶胞步：真精修晶胞（``refine_cell_full``，按晶系放自由分量）。

        顺序 —— 先按当前峰形解一次拿基准，再精修全晶胞，最后**用新晶胞
        重解一次**：

        1. ``solve`` 只为把 scale/背景/峰形对齐到当前晶胞（峰形参数此刻
           是上一批步骤的成果，晶胞引擎会把它当固定值）；
        2. ``refine_cell_full`` 只优化晶胞自由度，Rwp 口径与 ``solve``
           不同（它固定峰形、少一堆非线性参数），**不能**直接当作本步的
           ``rwp_after`` —— 那是「这一步没改峰形所以看起来变好」的假象；
        3. 回写新晶胞后再 ``solve`` 一次，记录的是「当前参数集合下、晶胞
           已更新」的真实 Rwp。后续步骤也从这个结果继续。
        """
        prm0 = prev.params if prev is not None else inputs.profile
        base = solve(RefineInputs(inputs.pattern, list(phases), prm0, cfg))
        try:
            # 用 base.pattern（已按 [tmin, tmax] 裁过）而不是 inputs.pattern：
            # 晶胞引擎内部不做裁剪，传入未裁谱会让窗口外零计算谱污染残差。
            cr = refine_cell_full(list(phases), base.pattern, base.params,
                                  cfg, backend=cfg.backend)
        except Exception as exc:
            rec = StepRecord(step.key, step.title, "failed",
                             None if prev is None else prev.rwp, base.rwp,
                             f"晶胞精修失败：{exc}")
            self.state.records.append(rec)
            return base, rec

        new_phases = [structure_with_cell(st, cell)
                      for st, cell in zip(phases, cr.cells)]
        res = solve(RefineInputs(inputs.pattern, new_phases, base.params, cfg))
        self._phases = new_phases

        before = None if prev is None else prev.rwp
        self.state.push_snapshot(res.params)
        rec = StepRecord(step.key, step.title, "done", before, res.rwp,
                         self._describe_cell_change(phases, new_phases, cfg),
                         snapshot=self.state.snapshots[-1])
        self.state.records.append(rec)
        return res, rec

    @staticmethod
    def _describe_cell_change(old: list[CifStructure],
                              new: list[CifStructure],
                              cfg: RefineConfig) -> str:
        """给结果区一句可读的晶胞变化摘要（最多列 3 个相）。"""
        from xinrefinement.core.refine.cell import crystal_system_of, free_axes

        parts: list[str] = []
        for a, b in zip(old, new):
            try:
                ndof = len(free_axes(crystal_system_of(b)))
            except Exception:
                ndof = 0
            dev = max((abs(y - x) / abs(x) * 100.0
                       for x, y in zip(a.cell, b.cell) if abs(x) > 1e-9),
                      default=0.0)
            parts.append(f"{b.name} Δ{dev:.3f}% / {ndof} 参")
        if len(parts) > 3:
            parts = parts[:3] + [f"另 {len(new) - 3} 相"]
        return f"{len(new)} 相晶胞已精修（" + "，".join(parts) + "）"

    def run_all(self, inputs: RefineInputs,
                steps: tuple[RefineStep, ...] | None = None,
                cancel_cb=None) -> tuple[SolveResult | None, list[StepRecord]]:
        """顺序连跑：每步以上一步参数为初值，收敛（ΔRwp<tol）可提前停。"""
        todo = steps if steps is not None else self.state.steps
        result: SolveResult | None = None
        self.state.current = 0
        self._phases = list(inputs.phases)
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
