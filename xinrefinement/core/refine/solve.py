"""M0 高层精修入口：``solve(inputs) -> SolveResult``（P1.0a 的起点）。

薄封装 P0 已 vendor 的变量投影引擎（``nonlinear.refine``），补齐：

- 输入/输出契约（``RefineInputs`` / ``SolveResult``）；
- 谱图按精修窗口 ``[tmin, tmax]`` 裁剪，避免窗口外零计算谱把 Rwp 拖坏；
- QPA 质量分数（Hill–Howard；化学式缺失时降级为 ``None`` 并给出 warning）；
- 结构化参数表 / 背景 / 收敛历史，供 CLI、报告导出、GUI 复用。

命名说明：plan/TASKS 写作 ``solve(inputs) -> RefineResult``；为不与引擎层
``nonlinear.RefineResult``（低层结果）重名，高层结果命名为 ``SolveResult``。

设计约束（沿用家族分层纪律）：
- 本模块不读写文件（``parse_cif`` / ``load_pattern`` 由调用方负责）；
- 只做编排与结果整形，不改动数值核心；
- ``solve`` 是未来 XinMatch 等外部调用方唯一需要依赖的入口。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.profile.cif import CifStructure
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import (
    RefineConfig,
    RefineResult as EngineResult,
    refine,
)
from xinrefinement.core.refine.qpa import (
    PhaseWeight,
    qpa_inputs_from_cif,
    qpa_weights,
)


@dataclass(frozen=True)
class RefineInputs:
    """一次精修的输入（相列表；单相即长度为 1）。"""

    pattern: Pattern
    phases: list[CifStructure]
    profile: ProfileParams = field(default_factory=ProfileParams)
    config: RefineConfig = field(default_factory=RefineConfig)
    #: 相名 -> 化学式；缺省逐个回退到 CIF 自带的 ``_chemical_formula_sum``。
    formulas: dict[str, str] | None = None


@dataclass(frozen=True)
class PhaseInfo:
    """单相的定量/晶胞摘要（供报告与 GUI 展示）。"""

    name: str
    formula: str | None
    scale: float
    weight_pct: float | None   # Hill–Howard 质量分数（%）；无法定量时 None
    z: int | None              # 晶胞内化学式单元数（QPA 反算）
    volume: float              # 晶胞体积（Å³）
    cell: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class SolveResult:
    """M0 精修结果契约（高层）。

    ``engine`` 保留引擎原始结果，便于 P1 扩展 e.s.d./相关性时直接取用。
    """

    rwp: float
    rp: float
    rexp: float
    chi2: float
    rbragg: float | None
    success: bool
    iters: int
    restarted: bool
    params: ProfileParams
    background: np.ndarray
    ycalc: np.ndarray
    phases: tuple[PhaseInfo, ...]
    history: tuple[float, ...]
    config: RefineConfig
    pattern: Pattern
    engine: EngineResult
    warnings: tuple[str, ...] = ()


def _clip_to_window(pat: Pattern, tmin: float, tmax: float,
                    warnings: list[str]) -> Pattern:
    """把谱图裁剪到精修窗口内（窗口外引擎计算谱恒为 0，会污染残差）。

    已在窗口内则原样返回，不复制数组。
    """
    tt = pat.two_theta
    if tt.size == 0:
        raise ValueError("谱图为空")
    if tt[0] >= tmin and tt[-1] <= tmax:
        return pat
    mask = (tt >= tmin) & (tt <= tmax)
    if not bool(mask.any()):
        raise ValueError(
            f"谱图区间 [{tt[0]:g}, {tt[-1]:g}]° 与精修窗口 "
            f"[{tmin:g}, {tmax:g}]° 无交集")
    warnings.append(
        f"谱图已裁剪到精修窗口 [{tmin:g}, {tmax:g}]°"
        f"（原区间 [{tt[0]:g}, {tt[-1]:g}]°）")
    return Pattern(two_theta=tt[mask].copy(), intensity=pat.intensity[mask].copy(),
                   meta=dict(pat.meta))


def _phase_weights(phases: list[CifStructure], scales: np.ndarray,
                   formulas: dict[str, str] | None,
                   warnings: list[str]) -> list[PhaseWeight] | None:
    """计算 Hill–Howard 质量分数；任一相缺化学式则整体降级为 None。"""
    formulas = formulas or {}
    triples: list[tuple[str, float, int, float, float]] = []
    for st in phases:
        f = formulas.get(st.name) or getattr(st, "formula", None)
        try:
            z, vol, mass = qpa_inputs_from_cif(st, f)
        except Exception as exc:  # 化学式缺失/解析失败 -> 降级
            warnings.append(f"QPA 跳过：相「{st.name}」无法定量（{exc}）")
            return None
        triples.append((st.name, float(scales[len(triples)]), z, vol, mass))
    try:
        return qpa_weights(triples)
    except Exception as exc:
        warnings.append(f"QPA 计算失败（{exc}）")
        return None


def _phase_infos(phases: list[CifStructure], engine: EngineResult,
                 weights: list[PhaseWeight] | None) -> tuple[PhaseInfo, ...]:
    infos: list[PhaseInfo] = []
    for i, st in enumerate(phases):
        fa, fc = engine.cell_scales[i] if i < len(engine.cell_scales) else (1.0, 1.0)
        a, b, c, al, be, ga = st.cell
        infos.append(PhaseInfo(
            name=st.name,
            formula=getattr(st, "formula", None),
            scale=float(engine.scales[i]),
            weight_pct=None if weights is None else float(weights[i].weight) * 100.0,
            z=None if weights is None else int(weights[i].Z),
            volume=float(st.volume),
            cell=(a * fa, b * fa, c * fc, al, be, ga),
        ))
    return tuple(infos)


def _resolve_interp_bg(cfg: RefineConfig, pat: Pattern,
                       warnings: list[str]) -> RefineConfig:
    """v1.2.0：``bg_mode="interp"`` 一次性提取锚点写回 ``bg_points``。

    提取是 O(N·iters) 的逐点统计，**绝不能**进残差热路径 —— 在这里做一次。
    bg_mode 保持 "interp"：MAUD 两层可加语义（固定插值曲线 + 其上自由
    Chebyshev）由 ``solve_linear_detail`` 的 interp 分支实现。
    """
    if cfg.bg_mode != "interp" or cfg.bg_points:
        return cfg
    from xinrefinement.core.refine.linear import interp_background_nodes
    pts = interp_background_nodes(pat.two_theta, pat.intensity,
                                  cfg.n_bg, cfg.bg_interp_iters)
    warnings.append(
        f"插值背景已自动提取 {len(pts)} 个锚点（迭代 {cfg.bg_interp_iters} 次，"
        "MAUD backgroundSubtraction 语义），固定层 + Chebyshev 两层可加")
    from dataclasses import replace as _replace
    return _replace(cfg, bg_points=tuple(pts))


def solve(inputs: RefineInputs) -> SolveResult:
    """执行一次全谱拟合（Rietveld / Le Bail 在 P2 扩展；M0 为 Rietveld）。

    变量投影：scale 与背景系数由线性层解析求解，LM 只迭代非线性峰形参数。
    线性窗口由 ``config.tmin/tmax`` 决定；谱图超出窗口时自动裁剪。
    """
    if not inputs.phases:
        raise ValueError("solve 至少需要一个物相")
    warnings: list[str] = []
    pat = _clip_to_window(inputs.pattern, inputs.config.tmin, inputs.config.tmax,
                          warnings)
    cfg = _resolve_interp_bg(inputs.config, pat, warnings)
    engine = refine(inputs.phases, pat, inputs.profile, cfg)
    weights = _phase_weights(inputs.phases, engine.scales, inputs.formulas,
                             warnings)
    return SolveResult(
        rwp=float(engine.rf.rwp),
        rp=float(engine.rf.rp),
        rexp=float(engine.rf.rexp),
        chi2=float(engine.rf.chi2),
        rbragg=engine.rf.rbragg,
        success=bool(engine.success),
        iters=int(engine.iters),
        restarted=bool(engine.restarted),
        params=engine.params,
        background=np.asarray(engine.bg, dtype=np.float64),
        ycalc=np.asarray(engine.ycalc, dtype=np.float64),
        phases=_phase_infos(inputs.phases, engine, weights),
        history=tuple(float(v) for v in engine.history),
        config=cfg,
        pattern=pat,
        engine=engine,
        warnings=tuple(warnings),
    )
