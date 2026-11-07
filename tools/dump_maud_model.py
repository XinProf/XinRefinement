"""把 7 样 MAUD ``*.par`` 的**逐相模型配置**抽成结构化表（诊断用，只读）。

动机
----
对标 MAUD 时最大的坑是「口径/模型不同却不自知」。Rwp 差 1.7–6 pt 究竟来自
峰形、织构、微结构还是结构模型，靠猜会浪费大量算力。本脚本只做一件事：
把 MAUD 侧**实际在用的模型开关与参数**（逐相织构模型、Delft/Popa 尺寸-应变、
晶粒尺寸/微应变、反相畴、全局峰形与背景开关）逐项打印/落 JSON，作为我们
改进项的靶点清单。

用法
----
    python tools/dump_maud_model.py            # 打印全部 7 样
    python tools/dump_maud_model.py --json     # 同时写 C:/Temp/maud_compare/v14/maud_model.json

解析策略
--------
``.par`` 是 CIF 风格文本，相与相之间用 ``_pd_phase_name`` 分隔；相内再嵌
``#subordinateObject_<name>`` 子对象块（tex / Delft / Isotropic / abm ...）。
这里不建完整 AST，只做「按相切片 + 逐键抓值」：``_pd_phase_name`` 之后、
下一个 ``_pd_phase_name`` 之前的所有 ``键 值`` 归该相。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(r"D:\Project\XRDdata\ShiJK-Refinement")
OUT = Path(r"C:/Temp/maud_compare/v14")

#: 每相关心的键（顺序即打印顺序）
PHASE_KEYS = (
    "_symmetry_space_group_name_H-M",
    "_cell_length_a",
    "_cell_length_b",
    "_cell_length_c",
    "_pd_proc_ls_pref_orient_corr",
    "_rita_harmonic_expansion_degree",
    "_riet_size_strain_model",
    "_riet_sizestrain_sym_model",
    "_riet_par_cryst_size",
    "_riet_par_rs_microstrain",
    "_riet_antiphase_boundary",
    "_riet_par_strain_thermal",
    "_maud_apply_micro_absorption",
    "_riet_par_microabsorption",
)

#: 全局（谱/精修）关心的键
GLOBAL_KEYS = (
    "_refine_ls_wR_factor_all",
    "_refine_ls_goodness_of_fit_all",
    "_pd_proc_ls_weight_scheme",
    "_pd_proc_ls_theoretical_weight",
    "_pd_proc_2theta_range_min",
    "_pd_proc_2theta_range_max",
    "_diffrn_inst_broadening",
    "_riet_caglioti_d_dep",
    "_riet_asymmetry_tan_dep",
    "_riet_par_asymmetry_truncation",
    "_riet_par_background_interpolated",
    "_riet_par_background_interpolation_range",
    "_maud_interpolated_background_iterations",
    "_rita_harmonic_expansion_degree",
    "_riet_size_strain_model",
    "_computing_refinement_algorithm",
    "_refine_ls_number_iteration",
    "_riet_refine_ls_lambda",
    "_riet_refine_ls_derivative_step",
    "_riet_par_sigma_calculation",
)

_LINE = re.compile(r"^\s*(_[A-Za-z0-9_.#\-]+)\s+(.+?)\s*$")


def _val(raw: str) -> str:
    """去掉 CIF 尾注释（``#positive #min 5.0``）与引号，只留第一个 token 组。"""
    s = raw.split("#")[0].strip()
    s = s.strip("'\"")
    return s


def parse_par(path: Path) -> dict:
    """返回 {"globals": {...}, "phases": [{"name":..., "keys": {...}}]}。"""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    globals_: dict[str, str] = {}
    phases: list[dict] = []
    cur: dict | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # ``#subordinateObject_xxx`` 也以 # 开头；不当作注释跳过整行
            if stripped.startswith("#subordinateObject_"):
                continue
            continue
        m = _LINE.match(line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        if key == "_pd_phase_name":
            cur = {"name": _val(raw), "keys": {}}
            phases.append(cur)
            continue
        if cur is not None and key in PHASE_KEYS:
            cur["keys"].setdefault(key, _val(raw))
        if key in GLOBAL_KEYS:
            globals_.setdefault(key, _val(raw))
    return {"globals": globals_, "phases": phases}


def _short(v: str | None, n: int = 42) -> str:
    if v is None:
        return "—"
    return v if len(v) <= n else v[: n - 1] + "…"


def _pick_par(d: Path) -> Path | None:
    """挑该目录里**真正收敛**的那份 ``.par``。

    MAUD 会留下中间态 ``<名>.par``（其 ``.lst`` 为空/不存在）：样 6 就有
    ``6#.par``（``_refine_ls_wR_factor_all 0.1589``，未收敛）与
    ``6b#.par``（``0.14764948``＝14.76%，项目记录的基线）两份。按文件名
    排序取第一个会拿到错的那份，故以「同名 ``.par.lst`` 非空」为准。
    """
    pars = sorted(d.glob("*.par"))
    if not pars:
        return None
    scored = []
    for p in pars:
        lst = p.with_name(p.name + ".lst")
        size = lst.stat().st_size if lst.exists() else 0
        scored.append((size > 0, size, p))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="写 maud_model.json")
    args = ap.parse_args()

    dirs = sorted((p for p in ROOT.iterdir() if p.is_dir()), key=lambda p: p.name)
    out: dict[str, dict] = {}
    for i, d in enumerate(dirs, 1):
        par = _pick_par(d)
        if par is None:
            print(f"[{i}] {d.name}: 无 .par，跳过")
            continue
        info = parse_par(par)
        info["par_file"] = par.name
        out[str(i)] = info
        g = info["globals"]
        print(f"\n===== 样 {i}  {d.name}  ← {par.name}")
        print(f"  Rwp {g.get('_refine_ls_wR_factor_all','?')}  "
              f"GOF {g.get('_refine_ls_goodness_of_fit_all','?')}  "
              f"窗口 [{g.get('_pd_proc_2theta_range_min','?')}, "
              f"{g.get('_pd_proc_2theta_range_max','?')}]")
        print(f"  权重 {g.get('_pd_proc_ls_weight_scheme','?')} "
              f"(theoretical={g.get('_pd_proc_ls_theoretical_weight','?')})  "
              f"峰形 {g.get('_diffrn_inst_broadening','?')} "
              f"d_dep={g.get('_riet_caglioti_d_dep','?')} "
              f"asym_tan={g.get('_riet_asymmetry_tan_dep','?')}"
              f"/{g.get('_riet_par_asymmetry_truncation','?')}")
        print(f"  背景 interp={g.get('_riet_par_background_interpolated','?')} "
              f"range={g.get('_riet_par_background_interpolation_range','?')} "
              f"iter={g.get('_maud_interpolated_background_iterations','?')}")
        for ph in info["phases"]:
            k = ph["keys"]
            print(f"    · {_short(ph['name'], 20):22s} "
                  f"SG={_short(k.get('_symmetry_space_group_name_H-M'), 12):13s} "
                  f"cell={_short(k.get('_cell_length_a'), 9)}/"
                  f"{_short(k.get('_cell_length_c'), 9)}")
            print(f"        tex={_short(k.get('_pd_proc_ls_pref_orient_corr'), 22):23s} "
                  f"deg={_short(k.get('_rita_harmonic_expansion_degree'), 5):6s} "
                  f"SS={_short(k.get('_riet_size_strain_model'), 9):10s} "
                  f"sym={_short(k.get('_riet_sizestrain_sym_model'), 11):12s}")
            print(f"        size={_short(k.get('_riet_par_cryst_size'), 14):15s} "
                  f"strain={_short(k.get('_riet_par_rs_microstrain'), 14):15s} "
                  f"abm={_short(k.get('_riet_antiphase_boundary'), 12)}")

    if args.json:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "maud_model.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写 {OUT / 'maud_model.json'}")


if __name__ == "__main__":
    main()
