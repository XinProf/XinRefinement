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
v1.4 当前 core 能力：零点 / 背景 / 标度 / 峰形 / 晶胞（P1.2）/
择优取向 / 原子坐标（P1.3，v1.4 接入配方）/ 每相 ΔB_iso（P1.4 的
温度因子部分）。占位精修仍未接入配方。

三个后加能力都是 **opt-in**：``xyz``、``B``、``po_probe`` 在
``RefineConfig`` 里默认关闭（CLI/API 零回归），GUI 只把 ``po_probe``
出厂默认开（实样收益见评估报告 §11.5）。步骤本身 ``available=True``，
但未被显式开启时 ``run_step`` 仍记 ``skipped`` —— 不做假执行。

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
from pathlib import Path

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.cell import refine_cell_full, structure_with_cell
from xinrefinement.core.refine.nonlinear import DEFAULT_PO_HKL, RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, SolveResult, solve

#: v1.4 #17 性能护栏：站点 LM 用数值雅可比，每次迭代要 O(n_free) 次
#: 「多相全谱 + 线性层」评估；实样 5 相体系按配方的 ``max_iter=40`` 会
#: 跑十几分钟仍不收敛。坐标精修一般 8–12 次即到平台，这里给 xyz 步
#: 单独封顶，避免一条配方链被站点引擎拖死（主 solve 的迭代预算不变）。
XYZ_SITE_MAX_ITER = 12


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
                       # v1.4 #18：调用方显式开启 refine_biso 时，B 步逐相
                       # 精修 ΔB_iso（solve 自动补 0 起点）；其余步一律关，
                       # 避免每步都把高角衰减当自由度抢峰形参数。
                       refine_biso=(self.key == "B" and cfg.refine_biso),
                       # v1.4 #17：xyz 步由独立站点引擎执行（不走 solve）
                       refine_xyz=(self.key == "xyz" and cfg.refine_xyz),
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
    RefineStep("xyz", "原子坐标", "xyz", True,
               "P1.3 已落地（Wyckoff 位约束）；需 --refine-xyz 显式开启，"
               "缺 CIF 源路径的相自动跳过"),
    RefineStep("B", "温度因子", "B", True,
               "v1.4 #18：每相 ΔB_iso（逐相高角衰减，占位精修仍待 P1.4）"),
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
        #: v1.4 #19：最近一次 micro 步 PO 试探的逐候选明细（诊断/测试用）
        self.po_probe_report: list[dict] = []
        #: v1.4 #17：最近一次 xyz 步的站点精修明细（诊断/测试用）
        self.xyz_report: dict = {}

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
        self.po_probe_report = []
        self.xyz_report = {}

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
        # v1.4 #17：xyz 步由独立站点引擎执行；未开启时按 skip 记录
        if step.key == "xyz":
            return self._run_xyz(step, inputs, prev, phases, cfg)
        # v1.4 #19：仅当调用方显式开启 po_probe 才走试探分支（默认关，
        # 与 v1.3 逐位一致）。
        if step.key == "micro" and inputs.config.po_probe:
            return self._run_micro(step, inputs, prev, phases, cfg)

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

    def _run_xyz(self, step: RefineStep, inputs: RefineInputs,
                 prev: SolveResult | None, phases: list[CifStructure],
                 cfg: RefineConfig) -> tuple[SolveResult | None, StepRecord]:
        """v1.4 #17：xyz 步调用独立站点引擎精修原子坐标。

        关键约束（全部来自 ``core.refine.site``）：

        - 重读 CIF **未展开**的不对称单位 + symop，用 site symmetry 的
          ``(R−I)`` 零空间求自由坐标方向；等价原子通过同一组 symop 联动，
          不会把对称性精修坏；
        - 已精修过的晶胞（cell 步产物）覆盖 ``SiteModel.cell``；
        - 没有 CIF 源路径的相作为 ``fixed_structures`` 常量基进入变量投影，
          避免它们的强度被算到被精修相的标度上；
        - 自由坐标系数超过 ``xyz_max_params`` 直接判失败（欠定护栏）；
        - 精修后**重新 solve 一次比较 Rwp**，没有改善就整体回退，不把
          结构改成更差的样子（这是配方层对用户的承诺）。
        """
        src = inputs.config
        prm0 = prev.params if prev is not None else inputs.profile
        # 单步执行（prev=None）时先解一次作为对照，否则"没有改善就回退"
        # 会因缺少基准 Rwp 把任何结果都判成回退。
        fallback = prev
        if prev is None:
            fallback = solve(replace(inputs,
                                     config=replace(cfg, refine_xyz=False),
                                     phases=phases, profile=prm0))
        before = float(fallback.rwp) if fallback is not None else None

        def _rec(status: str, msg: str, after=None,
                 res: SolveResult | None = None):
            rec = StepRecord(step.key, step.title, status, before, after, msg)
            self.state.records.append(rec)
            return res, rec

        if not src.refine_xyz:
            return _rec("skipped",
                        "P1.3 原子坐标精修未开启（--refine-xyz / micro 齿轮）",
                        before, prev)
        from xinrefinement.core.refine.site import (
            parse_site_model, refine_sites)

        models, fixed, index = [], [], []
        model_sources: list[CifStructure] = []
        for st in phases:
            path = getattr(st, "source_path", None)
            if path and Path(path).exists():
                try:
                    m = parse_site_model(path)
                except Exception:                              # noqa: BLE001
                    index.append(("fixed", len(fixed)))
                    fixed.append(st)
                    continue
                m = replace(m, name=st.name, cell=tuple(float(v) for v in st.cell),
                            formula=getattr(st, "formula", None),
                            spacegroup=getattr(st, "spacegroup", None),
                            sg_number=getattr(st, "sg_number", None))
                models.append(m)
                model_sources.append(st)
                index.append(("model", len(models) - 1))
            else:
                index.append(("fixed", len(fixed)))
                fixed.append(st)
        if not models:
            return _rec("skipped",
                        "P1.3 原子坐标精修：无相带 CIF 源路径（如 "
                        "parse_cif_string 构造的结构），已跳过",
                        before, prev)

        n_free = sum(int(s.n_free) for m in models for s in m.sites)
        if n_free > int(src.xyz_max_params):
            return _rec("failed",
                        f"原子坐标欠定：自由坐标系数 {n_free} > "
                        f"xyz_max_params={src.xyz_max_params}", None, prev)

        # 站点引擎不裁剪谱图，且线性背景口径要与主 solve 一致
        pat = (prev.pattern if prev is not None else inputs.pattern)
        mask = ((pat.two_theta >= src.tmin) & (pat.two_theta <= src.tmax))
        clip = replace(pat, two_theta=pat.two_theta[mask],
                       intensity=pat.intensity[mask])
        backend = "lm" if src.backend in ("", "lm") else "scipy"
        site_cfg = replace(src, max_iter=min(int(src.max_iter),
                                             XYZ_SITE_MAX_ITER))
        try:
            sr = refine_sites(models, clip, prm0, site_cfg, backend=backend,
                              free_kinds=("xyz",), fixed_structures=fixed)
        except Exception as exc:                              # noqa: BLE001
            return _rec("failed", f"原子坐标精修失败：{exc}", None, prev)

        new_phases, mi, fi = [], 0, 0
        for kind, _j in index:
            if kind == "model":
                st_new = sr.structures[mi]
                src_st = model_sources[mi]
                mi += 1
                # 站点引擎由「未展开不对称单位」重建结构，to_structure 只回填
                # formula/spacegroup；QPA 的 z_declared 与对称性/源路径元数据
                # 必须逐项继承，否则精修后定量静默退化、下一轮 xyz 步找不到 CIF。
                for attr in ("z_declared", "n_asym", "n_sym_ops",
                             "source_path"):
                    if hasattr(src_st, attr):
                        setattr(st_new, attr, getattr(src_st, attr))
                new_phases.append(st_new)
            else:
                new_phases.append(fixed[fi]); fi += 1
        try:
            res = solve(replace(inputs, config=replace(cfg, refine_xyz=False),
                                phases=new_phases, profile=prm0))
        except Exception as exc:                              # noqa: BLE001
            return _rec("failed", f"原子坐标精修后重解失败：{exc}", None, prev)

        if before is not None and res.rwp >= before - 1e-9:
            self.xyz_report = {"params": tuple(float(v) for v in sr.params),
                               "rwp": float(sr.rwp), "success": bool(sr.success),
                               "n_free": n_free,
                               "phases": [m.name for m in models],
                               "accepted": False}
            return _rec("done",
                        f"原子坐标精修未改善 Rwp（{res.rwp:.3f} ≥ "
                        f"{before:.3f}），已回退原结构",
                        before, fallback)
        drift = max((abs(float(v)) for v in sr.params), default=0.0)
        self.xyz_report = {"params": tuple(float(v) for v in sr.params),
                           "rwp": float(sr.rwp), "success": bool(sr.success),
                           "n_free": n_free, "phases": [m.name for m in models],
                           "accepted": True}
        msg = (f"原子坐标：{len(models)} 相 / {n_free} 个自由系数，"
               f"Rwp {before:.3f} → {res.rwp:.3f}，最大位移 {drift:.4f}")
        if drift > 0.03:
            msg += "（位移偏大，建议核查结构模型）"
        self._phases = new_phases
        self.state.push_snapshot(res.params)
        rec = StepRecord(step.key, step.title, "done", before, res.rwp, msg,
                         snapshot=self.state.snapshots[-1])
        self.state.records.append(rec)
        return res, rec

    def _run_micro(self, step: RefineStep, inputs: RefineInputs,
                   prev: SolveResult | None, phases: list[CifStructure],
                   cfg: RefineConfig) -> tuple[SolveResult | None, StepRecord]:
        """v1.4 #19：micro 步先自动试探 March–Dollase 惯习面，再正式精修。

        为什么有这一步：实样对拍（§11.2）里样品 3 的 CaF₂(111) 择优取向
        一项就值 −12.06 个百分点，但引擎只有在 ``prm.po_r`` 里**预先填好**
        (h,k,l) 才会精修 r —— 出厂配方没有这些信息，micro 步等于空转。

        流程（全部由配方层编排，``solve``/registry 接口不变）：

        1. 以当前参数为初值，关掉除 po 以外的全部非线性自由度；
        2. 对「用户未配置 po_r、且未开 EWIMV 织构」的每一相，逐个候选轴
           短精修 r（每个候选只有 1 个有效自由度），记录 Rwp 增益；
        3. 增益 ≥ ``po_probe_min_gain`` 的相按增益降序取前
           ``po_probe_max_phases`` 个（同一相只留最佳轴），把 ``r=1`` 写入
           po_r，交给正式 micro 步连同 X/Y 一起精修；
        4. 试探细节存 ``self.po_probe_report``，并写入 StepRecord.message。

        试探本身是启发式（不是统计检验），阈值默认 0.3 个百分点用于挡噪声。
        ``po_probe=False``（默认）时 ``run_step`` 完全不走这里，逐位零回归。
        """
        src = inputs.config
        prm0 = prev.params if prev is not None else inputs.profile
        existing = dict(prm0.po_r or {})
        tex_names = set(prm0.texture or {})
        # 只放 r：其余非线性参数保持当前值，避免试探把峰形改动算成 PO 收益
        probe_cfg = replace(
            cfg, refine_zero=False, refine_uvw=False, refine_eta=False,
            refine_asym=False, refine_bfactor=False, refine_cell=False,
            refine_size=False, refine_strain=False, refine_texture=False,
            refine_aniso=False, refine_microabs=False, refine_po=True,
            po_probe=False, max_iter=int(src.po_probe_max_iter))
        base_cfg = replace(probe_cfg, refine_po=False)
        try:
            base_rwp = float(solve(RefineInputs(
                inputs.pattern, phases, prm0, base_cfg)).rwp)
        except Exception:                                          # noqa: BLE001
            base_rwp = float(prev.rwp) if prev is not None else float("inf")

        report: list[dict] = []
        for st in phases:
            # DEFAULT_PO_HKL 覆盖的相由 nonlinear._ensure_po_r 自动补已知
            # 惯习面（锐钛 (001) / 金红石 (110)）；若让试探覆盖它，实测会把
            # 更准的默认轴换成噪声轴（合成对照 Rwp 5.4235 → 5.4265）。
            if (st.name in existing or st.name in tex_names
                    or st.name in DEFAULT_PO_HKL):
                continue
            for axis in src.po_probe_axes:
                hkl = tuple(int(v) for v in axis[:3])
                if hkl == (0, 0, 0):
                    continue
                prm = replace(prm0, po_r={**existing,
                                          st.name: (*hkl, 1.0)})
                try:
                    res = solve(RefineInputs(
                        inputs.pattern, phases, prm, probe_cfg))
                    gain = base_rwp - float(res.rwp)
                    r = (float(res.params.po_r[st.name][3])
                         if res.params.po_r else 1.0)
                    report.append({"phase": st.name, "axis": list(hkl),
                                   "rwp_pct": float(res.rwp),
                                   "gain": gain, "r": r,
                                   "success": bool(res.success)})
                except Exception as exc:                          # noqa: BLE001
                    report.append({"phase": st.name, "axis": list(hkl),
                                   "rwp_pct": None, "gain": None,
                                   "error": f"{type(exc).__name__}: {exc}"})

        self.po_probe_report = report
        best_per_phase: dict[str, dict] = {}
        for row in report:
            g = row.get("gain")
            if g is None or g < float(src.po_probe_min_gain):
                continue
            cur = best_per_phase.get(row["phase"])
            if cur is None or g > cur["gain"]:
                best_per_phase[row["phase"]] = row
        accepted = sorted(best_per_phase.values(),
                          key=lambda r: -r["gain"])[:max(1, int(
                              src.po_probe_max_phases))]
        po_r = dict(existing)
        for row in accepted:
            po_r[row["phase"]] = (*tuple(row["axis"]), 1.0)
        prm_final = replace(prm0, po_r=(po_r or None))
        msg = ("PO 试探：" + ("；".join(
            f"{r['phase'][:18]}({''.join(str(v) for v in r['axis'])}) "
            f"−{r['gain']:.2f}pt" for r in accepted)
            if accepted else "无相达到增益阈值，未启用 PO"))

        inp = replace(inputs, config=cfg, phases=phases, profile=prm_final)
        try:
            res = solve(inp)
        except Exception as exc:                                  # noqa: BLE001
            rec = StepRecord(step.key, step.title, "failed",
                             None if prev is None else prev.rwp, None,
                             f"{msg}；正式精修失败：{exc}")
            self.state.records.append(rec)
            return prev, rec
        before = None if prev is None else prev.rwp
        self.state.push_snapshot(res.params)
        rec = StepRecord(step.key, step.title, "done", before, res.rwp,
                         msg, snapshot=self.state.snapshots[-1])
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
        self.po_probe_report = []
        self.xyz_report = {}
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
