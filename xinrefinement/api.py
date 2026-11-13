"""P4.6 · 公开库 API 契约（XinMatch 等外部调用方的唯一入口）。

设计：外部只需 ``from xinrefinement import api``，调
``api.refine(pattern, cifs, ...)`` 即可完成一次精修并拿到结构化结果；
内部实现（vendor 引擎、注册表、GUI）可自由演进，不破坏该契约。

版本化约定
----------
``API_VERSION`` 语义化版本；不兼容变更必须升主版本。所有返回对象提供
``as_dict()``，保证可 JSON 序列化（无 ndarray 泄漏）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xinrefinement import __version__

API_VERSION = "1.0.0"


@dataclass(frozen=True)
class RefineRequest:
    """外部调用方的输入契约。"""

    pattern: str | Path
    cifs: tuple[str | Path, ...]
    tmin: float = 5.0
    tmax: float = 90.0
    anode: str | None = "Cu"
    formulas: dict[str, str] | None = None
    refine_po: bool = False
    peak_height: bool = False       # 合成/峰高口径谱用 True
    #: v1.7 非晶宽包分量 ``((中心2θ, 半高宽), ...)``；峰高由线性层求解
    amorphous: tuple = ()

    def as_dict(self) -> dict:
        return {"pattern": str(self.pattern),
                "cifs": [str(c) for c in self.cifs],
                "tmin": self.tmin, "tmax": self.tmax,
                "anode": self.anode, "formulas": self.formulas,
                "refine_po": self.refine_po, "peak_height": self.peak_height,
                "amorphous": [list(a) for a in self.amorphous]}


@dataclass(frozen=True)
class RefineResponse:
    """外部调用方的输出契约（全部可 JSON 序列化）。"""

    api_version: str
    app_version: str
    rwp: float
    rp: float
    rexp: float
    chi2: float
    success: bool
    phases: tuple[dict, ...]
    parameters: dict
    warnings: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "api_version": self.api_version, "app_version": self.app_version,
            "r_factors": {"rwp": self.rwp, "rp": self.rp,
                          "rexp": self.rexp, "chi2": self.chi2},
            "success": self.success, "phases": list(self.phases),
            "parameters": self.parameters, "warnings": list(self.warnings),
        }


def refine(request: RefineRequest) -> RefineResponse:
    """一次全谱拟合（同步；外部可自行放进线程/进程）。"""
    from xinrefinement.core.patterns import load_pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import ProfileParams
    from xinrefinement.core.refine.nonlinear import RefineConfig
    from xinrefinement.core.refine.solve import RefineInputs, solve

    if not request.cifs:
        raise ValueError("RefineRequest.cifs 不能为空")
    pat = load_pattern(Path(request.pattern))
    phases = [parse_cif(Path(c)) for c in request.cifs]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode=request.anode, integrated=not request.peak_height)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True,
                       refine_po=request.refine_po,
                       n_bg=3, max_iter=40,
                       amorphous=tuple(tuple(float(v) for v in a)
                                       for a in (request.amorphous or ())),
                       tmin=request.tmin, tmax=request.tmax)
    res = solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                             config=cfg, formulas=request.formulas))
    p = res.params
    return RefineResponse(
        api_version=API_VERSION, app_version=__version__,
        rwp=res.rwp, rp=res.rp, rexp=res.rexp, chi2=res.chi2,
        success=res.success,
        phases=tuple({"name": ph.name, "scale": ph.scale,
                      "weight_pct": ph.weight_pct, "cell": list(ph.cell)}
                     for ph in res.phases),
        parameters={"zero": p.zero, "U": p.U, "V": p.V, "W": p.W,
                    "eta": p.eta, "X": p.X, "Y": p.Y,
                    "anode": p.anode, "wavelength": p.wavelength},
        warnings=res.warnings)


def quant(request: RefineRequest) -> dict:
    """只取定量结果（物相含量）。"""
    r = refine(request)
    return {"api_version": API_VERSION,
            "phases": [{"name": p["name"], "weight_pct": p["weight_pct"]}
                       for p in r.phases]}


def report(request: RefineRequest, out_dir: str | Path) -> dict[str, str]:
    """精修并导出 HTML/PNG/JSON 报告。"""
    from xinrefinement.core.report import export_report as _export
    # 报告路径调用 _solve_raw() 独立读盘求解，不与 refine() 共享中间结果
    res = _solve_raw(request)
    return _export(res, out_dir)


def _solve_raw(request: RefineRequest):
    """内部：返回 SolveResult（供 report 复用）。"""
    from xinrefinement.core.patterns import load_pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import ProfileParams
    from xinrefinement.core.refine.nonlinear import RefineConfig
    from xinrefinement.core.refine.solve import RefineInputs, solve
    pat = load_pattern(Path(request.pattern))
    phases = [parse_cif(Path(c)) for c in request.cifs]
    prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                        anode=request.anode,
                        integrated=not request.peak_height)
    cfg = RefineConfig(refine_zero=True, refine_uvw=True,
                       refine_po=request.refine_po,
                       n_bg=3, max_iter=40,
                       amorphous=tuple(tuple(float(v) for v in a)
                                       for a in (request.amorphous or ())),
                       tmin=request.tmin, tmax=request.tmax)
    return solve(RefineInputs(pattern=pat, phases=phases, profile=prm,
                              config=cfg, formulas=request.formulas))


def capabilities() -> dict:
    """返回当前 API 能力清单（便于调用方做版本协商）。"""
    return {
        "api_version": API_VERSION, "app_version": __version__,
        "entrypoints": ["refine", "quant", "report", "capabilities"],
        "radiation": "X-ray (Cromer-Mann f0), Cu/Co/Cr/Fe/Mo/Ag Kα1/α2 + mono",
        "geometry": "Bragg-Brentano",
        "quant": "Hill-Howard QPA",
        "engines": ["builtin variable-projection LM/scipy-trf"],
        # v1.1.0 联合计划：可导入 XinMatch 物相分析状态（.xinm）
        "xinm_import": "1",
        # v1.7：非晶宽包物理分量（RefineRequest.amorphous）
        "amorphous_hump": "1",
    }
