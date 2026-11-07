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
    ANISO_MIN_DIRS,
    ANISO_SEED_Y,
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


def _resolve_theoretical_sigma(cfg: RefineConfig, phases: list[CifStructure],
                               prm: ProfileParams, pat: Pattern,
                               warnings: list[str]) -> RefineConfig:
    """v1.3：``weight_mode="theoretical"`` 一次性解析为固定 σ 数组。

    MAUD theoreticalWeights：σ=√max(ycalc,1)，用**计算值**代替观测值定权
    （抗弱峰噪声漂移）。σ 依赖 ycalc、ycalc 依赖精修结果 —— 鸡生蛋，故在
    引擎入口**引导一次**：用初始参数 + 观测值引导权（√max(y_o,1)）解一遍
    线性层得 ycalc₀，再取 σ=√max(ycalc₀,1) 写入 ``cfg.sigma``。此后引擎/
    e.s.d./Rwp 全部走既有 ``cfg.sigma`` 路径，口径自动一致。静态 σ（不在
    迭代中滚动更新）保证残差函数确定性，有限差分 Jacobian 不受权重抖动污染。
    """
    if cfg.weight_mode != "theoretical" or cfg.sigma is not None:
        return cfg
    from xinrefinement.core.refine.linear import background_basis, \
        solve_linear_detail
    from xinrefinement.core.refine.nonlinear import effective_sigma, \
        _scaled, compute_phase_profile

    tt, yo = pat.two_theta, pat.intensity
    sig0 = effective_sigma(cfg, pat)          # 引导权（ycalc 省略 → √max(y_o,1)）
    rows = [compute_phase_profile(_scaled(st, 1.0, 1.0), tt, prm,
                                  cfg.tmin, cfg.tmax) for st in phases]
    _c, ycalc0, _d = solve_linear_detail(
        np.vstack(rows), tt, yo, sig0, cfg.n_bg, cfg.bg_mode,
        bg_points=list(cfg.bg_points) or None)
    sig = np.sqrt(np.maximum(ycalc0, 1.0))
    warnings.append(
        "theoreticalWeights：σ=√max(ycalc₀,1) 已由初始参数引导解析"
        "（MAUD theoreticalWeights 语义，静态 σ）")
    from dataclasses import replace as _replace
    return _replace(cfg, sigma=sig)


def _resolve_texture(cfg: RefineConfig, phases: list[CifStructure],
                     prm: ProfileParams,
                     warnings: list[str]) -> ProfileParams:
    """v1.3 任务 #14：织构配置的入口校验与规范化（一次性，不进热路径）。

    - 网格统一规范成 ``TEXTURE_N_GRID`` 点（CLI/GUI 可给任意长度）；
    - 相内独立 χ 桶数 < 3 → **显式报错**（欠定，不能静默给结果）；
    - 开织构的相与 March–Dollase 互斥，给出 warning（该相 r 被忽略）；
    - 未配置织构却开了开关 → 忽略并提示（不静默改变模型）。

    v1.5 M3：按 ``entry["model"]`` 分派——``"harmonic"``（球谐）只规范
    ``degree``/``coeffs``，不写 19 点 ``grid``；其可辨识性判据为
    「χ 桶数 ≥ 系数个数 + 1」。
    """
    from dataclasses import replace as _replace

    from xinrefinement.core.profile.forward import (
        DEFAULT_TEXTURE_AXIS,
        normalize_texture_grid,
        texture_chi_buckets,
        texture_coeffs,
        texture_model,
        texture_n_params,
    )

    if not prm.texture:
        if cfg.refine_texture:
            warnings.append(
                "织构精修已开启，但没有相配置织构轴 —— 该参数组不参与")
        return prm
    # 注：即使未开精修（cfg.refine_texture=False），配置的 T(χ) 仍作为
    # **固定因子**施加到前向模型——这里统做规范化与互斥检查。
    names = {st.name for st in phases}
    tex: dict[str, dict] = {}
    for name in sorted(prm.texture):
        if name not in names:
            warnings.append(f"织构配置的相「{name}」不在本次精修相列表，已忽略")
            continue
        entry = dict(prm.texture[name])
        axis = entry.get("axis") or DEFAULT_TEXTURE_AXIS
        entry["axis"] = (int(axis[0]), int(axis[1]), int(axis[2]))
        # v1.5 M3：按模型分派规范化。球谐只规范 degree/coeffs（**不能**顺手
        # 写 19 点 grid，否则 texture_n_params 与实际自由度脱节、pack/bounds 错位）
        if texture_model(entry) == "harmonic":
            entry["model"] = "harmonic"
            entry["coeffs"] = texture_coeffs(entry)
        else:
            entry["model"] = "ewimv"
            entry["grid"] = normalize_texture_grid(entry.get("grid"))
        tex[name] = entry
    if not tex:
        return _replace(prm, texture=None)
    for st in phases:
        entry = tex.get(st.name)
        if entry is None:
            continue
        if not cfg.refine_texture:
            continue
        n_buckets, _chis = texture_chi_buckets(
            st, prm, entry["axis"], cfg.tmin, cfg.tmax)
        if texture_model(entry) == "harmonic":
            n_coef = texture_n_params(entry)
            need = n_coef + 1
            if n_buckets < need:
                raise ValueError(
                    f"相「{st.name}」球谐织构欠定：窗口内独立 χ 桶数 "
                    f"{n_buckets} < {need}（{n_coef} 个系数至少需要 {need} 个"
                    "不同 χ 才可辨识，请降低展开阶数或改织构轴/窗口）")
        elif n_buckets < 3:
            raise ValueError(
                f"相「{st.name}」开织构欠定：窗口内独立 χ 桶数 {n_buckets} < 3，"
                "T(χ) 形状不可分辨（请改织构轴或调整精修窗口）")
        if prm.po_r and st.name in prm.po_r:
            _mdl = ("球谐 ODF（M3）" if texture_model(entry) == "harmonic"
                    else "EWIMV 离散 ODF")
            warnings.append(
                f"织构：相「{st.name}」已开{_mdl}，"
                "March–Dollase r 被忽略（两模型互斥）")
    if cfg.refine_texture:
        n_h = sum(1 for e in tex.values() if texture_model(e) == "harmonic")
        if n_h:
            orders = sorted({len(texture_coeffs(e)) * 2 for e in tex.values()
                             if texture_model(e) == "harmonic"})
            warnings.append(
                f"球谐织构（M3）：{n_h} 相 × 阶 "
                f"{'/'.join(str(d) for d in orders)}"
                "（Legendre 展开＝MAUD Harmonic 模型在纤维对称下的精确子空间）")
        if len(tex) - n_h:
            warnings.append(
                f"EWIMV 织构：{len(tex) - n_h} 相 × "
                f"{cfg.texture_lambda:g} 光滑罚权重"
                "（MAUD 离散 ODF 语义，BB 几何退化为每反射 T(χ)）")
    return _replace(prm, texture=tex)


def _resolve_aniso(cfg: RefineConfig, phases: list[CifStructure],
                   prm: ProfileParams,
                   warnings: list[str]) -> tuple[RefineConfig, ProfileParams]:
    """v1.3 任务 #15：Popa LB 各向异性配置的入口校验（一次性）。

    - 系数统一补齐/截断为 6 个（``size`` 与 ``strain`` 各 6）；
    - 开精修时要求窗口内独立晶向数 ≥ :data:`nl.ANISO_MIN_DIRS`，否则**报错**
      （12 个系数在方向不足时不可辨识，静默给结果等于给噪声）；
    - 给出各向异性比作为诊断（Dmax/Dmin、εmax/εmin）。

    v1.5 M4：``cfg.aniso_auto`` 为真时**自动为缺系数的相补各向同性起点**
    （:func:`aniso_default`，以当前标量 X/Y 为种），并把 ``refine_aniso``
    置为生效；自动补的相若方向数不足则**跳过该相**（不整体报错——自动模式
    不该让一次精修失败），显式配置的相仍按硬护栏报错。
    """
    from dataclasses import replace as _replace

    from xinrefinement.core.profile.forward import (
        aniso_default, aniso_dirs, aniso_ratios)

    auto = bool(getattr(cfg, "aniso_auto", False))
    auto_names: set[str] = set()
    if auto:
        cfg = _replace(cfg, refine_aniso=True)
        have = dict(prm.aniso or {})
        seed_y = float(prm.Y) if float(prm.Y) > 0 else ANISO_SEED_Y
        for st in phases:
            if st.name in have:
                continue
            have[st.name] = aniso_default(prm.wavelength, float(prm.X),
                                          seed_y)
            auto_names.add(st.name)
        if auto_names:
            prm = _replace(prm, aniso=have)
            shown = "、".join(sorted(auto_names)[:3])
            warnings.append(
                f"Popa LB 自动启用（M4）：{len(auto_names)} 相补各向同性起点"
                f"（{shown}{'…' if len(auto_names) > 3 else ''}），"
                f"size 6 参/相，起点取标量 X={prm.X:g}°、Y={seed_y:g}°")

    if not prm.aniso:
        if cfg.refine_aniso:
            warnings.append(
                "各向异性精修已开启，但没有相配置系数 —— 该参数组不参与")
        return cfg, prm
    names = {st.name for st in phases}
    out: dict[str, dict] = {}
    for name in sorted(prm.aniso):
        if name not in names:
            warnings.append(f"各向异性配置的相「{name}」不在本次精修相列表，已忽略")
            continue
        entry = prm.aniso[name] or {}
        out[name] = {
            "size": (list(entry.get("size") or []) + [0.0] * 6)[:6],
            "strain": (list(entry.get("strain") or []) + [0.0] * 6)[:6],
        }
    if not out:
        return cfg, _replace(prm, aniso=None)
    if cfg.refine_aniso:
        for st in phases:
            if st.name not in out:
                continue
            dirs = aniso_dirs(st, prm, cfg.tmin, cfg.tmax)
            n_dirs = int(dirs.shape[0])
            if n_dirs < ANISO_MIN_DIRS:
                if st.name in auto_names:
                    warnings.append(
                        f"Popa LB 自动启用：相「{st.name}」窗口内独立晶向 "
                        f"{n_dirs} 个 < {ANISO_MIN_DIRS}，跳过该相"
                        "（无法辨识，请扩大窗口或改用显式配置）")
                    out.pop(st.name, None)
                    continue
                raise ValueError(
                    f"相「{st.name}」各向异性欠定：窗口内独立晶向 {n_dirs} 个 "
                    f"< {ANISO_MIN_DIRS}（12 个二次型系数不可辨识，请扩大窗口）")
            d_ratio, e_ratio = aniso_ratios(out[st.name])
            mode = getattr(cfg, "aniso_mode", "size")
            warnings.append(
                f"Popa LB（mode={mode}）：相「{st.name}」{n_dirs} 个独立晶向，"
                f"Dmax/Dmin={d_ratio:.2f}，εmax/εmin={e_ratio:.2f}")
            if mode == "both":
                warnings.append(
                    "Popa LB：size 与 strain 同时精修存在互相吸收风险，"
                    "建议先只放 size（aniso_mode=\"size\"）再视残差决定")
    if not out:
        warnings.append("Popa LB：没有可辨识的相，该参数组不参与")
        return cfg, _replace(prm, aniso=None)
    return cfg, _replace(prm, aniso=out)


def _resolve_biso(cfg: RefineConfig, phases: list[CifStructure],
                  prm: ProfileParams, warnings: list[str]) -> ProfileParams:
    """v1.4 #18：每相 ΔB_iso 的入口校验与可辨识性提示（一次性，不进热路径）。

    - 缺省相补 0 起点（COD CIF 的 B_iso 全为 0）；
    - 高角数据不足（tmax<60°）时 B 与峰形/背景强相关，显式提示；
    - 与全局 bfactor 同时开会完全重叠一个自由度，提示只保留其一。
    """
    from dataclasses import replace as _replace

    from xinrefinement.core.refine.nonlinear import BISO_BOUNDS, _ensure_biso

    if not cfg.refine_biso:
        return prm
    b = _ensure_biso(phases, prm, cfg)
    if float(cfg.tmax) < 60.0:
        warnings.append(
            "ΔB_iso：精修窗口上限 < 60°，高角信息不足，"
            "温度因子与峰形/背景可能不可分辨（建议放宽窗口）")
    if cfg.refine_bfactor:
        warnings.append(
            "ΔB_iso：全局 bfactor 同时开启，两者作用形式完全相同，"
            "自由度重叠（建议只开 refine_biso）")
    warnings.append(
        f"ΔB_iso：{len(b or {})} 相逐相精修，上界 "
        f"{BISO_BOUNDS[1]:g} Å²；只压高角、不改峰位")
    return _replace(prm, b_iso=b)


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
    cfg = _resolve_theoretical_sigma(cfg, inputs.phases, inputs.profile, pat,
                                     warnings)
    prm = _resolve_texture(cfg, inputs.phases, inputs.profile, warnings)
    cfg, prm = _resolve_aniso(cfg, inputs.phases, prm, warnings)
    prm = _resolve_biso(cfg, inputs.phases, prm, warnings)
    engine = refine(inputs.phases, pat, prm, cfg)
    # v1.4 #18 实样基准护栏：ΔB_iso 顶到上界时，该相的高角失配多半不是
    # 温度因子，而是择优取向 / 织构 / 标度的模型误差被 B 吸收（7 样复测里
    # 4 样出现，且撞界相与 PO 收益相高度重合）。必须显式提示，不能让用户
    # 把一个过拟合参数当成物理 B 值。
    if cfg.refine_biso and getattr(engine.params, "b_iso", None):
        from xinrefinement.core.refine.nonlinear import BISO_BOUNDS as _BB

        hit = [str(k) for k, v in engine.params.b_iso.items()
               if float(v) >= _BB[1] - 1e-6]
        if hit:
            warnings.append(
                f"ΔB_iso：{len(hit)} 相顶到上界 {_BB[1]:g} Å²（"
                + "、".join(hit[:3]) + ("…" if len(hit) > 3 else "")
                + "）；高角失配可能来自择优取向/织构/标度误差被 B 吸收，"
                  "建议先确认 PO 与织构再启用 B 步；也可能是该相**结构模型**"
                  "与样品不符（多型/占位/无序）——实测样品 7 换成低对称"
                  "方石英多型后 Rwp −1.84 pt 且撞界同时消失")
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
