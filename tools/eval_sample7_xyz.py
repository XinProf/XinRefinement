"""v1.5 M8 后续：样 7「按相选择 xyz」可行性验证（只读实验，不改产品代码）。

背景
----
``combo_tex_aniso.json`` 里样 7 的 ``xyz`` 步是 **failed**：

    'xyz', 'failed', None, '原子坐标欠定：自由坐标系数 48 > xyz_max_params=40'

配方层对 ``n_free`` 做的是**全局求和**，超限就整步回退——于是 5 个相的
原子坐标一个都没精修。MAUD 侧对高岭石（P1）等相是精修坐标的。样 7 因此
白白丢掉一整步自由度，这很可能比织构/宽包更值钱。

``core.refine.site.refine_sites`` 已支持 ``fixed_structures``（不参与精修的相
作为常量基进入变量投影），所以「把超限的相转为 fixed、其余照常精修」是
天然可实现的降级路径，不需要动前向模型。

本脚本用增量口径（cell 步精修晶胞 + 全部非线性关）比较几种「哪些相参与
xyz 精修」的分组，给出 Rwp 与耗时，用来判断值得保留哪一组。

用法::

    python tools/eval_sample7_xyz.py              # 默认跑全部分组
    python tools/eval_sample7_xyz.py --list       # 只列每相自由坐标数

输出 ``C:\\Temp\\maud_compare\\v14\\s7_xyz.json``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_v14 as B                                             # noqa: E402
from xinrefinement.core.refine.recipe import XYZ_SITE_MAX_ITER    # noqa: E402
from xinrefinement.core.refine.site import (                      # noqa: E402
    parse_site_model, refine_sites)
from xinrefinement.core.refine.solve import RefineInputs, solve   # noqa: E402

OUT = B.OUT
D7 = sorted(p for p in B.ROOT.iterdir() if p.is_dir())[6]

#: 相的 CIF 源路径 -> 是否参与精修，按「自由坐标数升序」贪心留到预算内
META_ATTRS = ("z_declared", "n_asym", "n_sym_ops", "source_path")


def _site_models(phases):
    """返回 [(phase, model|None, n_free)]，与 recipe._run_xyz 同构造。"""
    out = []
    for st in phases:
        path = getattr(st, "source_path", None)
        if not path or not Path(path).exists():
            out.append((st, None, 0))
            continue
        try:
            m = parse_site_model(path)
        except Exception:                                         # noqa: BLE001
            out.append((st, None, 0))
            continue
        m = replace(m, name=st.name, cell=tuple(float(v) for v in st.cell),
                    formula=getattr(st, "formula", None),
                    spacegroup=getattr(st, "spacegroup", None),
                    sg_number=getattr(st, "sg_number", None))
        out.append((st, m, sum(int(s.n_free) for s in m.sites)))
    return out


def _groups(items, budget: int) -> dict[str, set[int]]:
    """按名字给出几组待比较的「参与精修相」下标集合。"""
    names = [st.name for st, _m, _n in items]
    nf = [n for _s, _m, n in items]
    total = sum(nf)
    # 最大自由度的相（预期是高岭石 P1）
    big = max(range(len(items)), key=lambda j: nf[j])
    # 贪心：自由坐标数小的相优先，累计不超过 budget
    order = sorted((j for j, n in enumerate(nf) if n > 0), key=lambda j: nf[j])
    greedy: set[int] = set()
    acc = 0
    for j in order:
        if acc + nf[j] <= budget:
            greedy.add(j)
            acc += nf[j]
    return {
        "none": set(),
        "all": set(range(len(items))),
        "drop_biggest": set(range(len(items))) - {big},
        "only_biggest": {big},
        "greedy_budget": greedy,
    }


def main(argv: list[str]) -> int:
    pat = B._load(7, D7, D7)[0]
    b = B._load_base(7)
    cfg0 = B._only(b["cfg"])
    phases = list(B._refined_phases(7, D7, D7))
    # 工程约束：cell 步重建结构会丢 source_path（缓存 base_7_phases.pkl 是
    # 老版本生成的）。xyz 引擎靠 source_path 找 CIF 不对称单位，必须按相名
    # 从原始 CIF 回填，否则 5 相全被判 fixed、n_free 恒为 0。
    raw = {st.name: st for st in B._load(7, D7, D7)[1]}
    for st in phases:
        src = raw.get(st.name)
        if src is not None:
            for attr in META_ATTRS:
                if hasattr(src, attr):
                    setattr(st, attr, getattr(src, attr))
    items = _site_models(phases)
    print("每相自由坐标数：")
    for st, _m, n in items:
        print(f"  {n:3d}  {st.name}")
    print(f"  合计 {sum(n for _s, _m, n in items)} / 预算 {b['cfg'].xyz_max_params}")
    if "--list" in argv:
        return 0

    budget = int(b["cfg"].xyz_max_params)
    groups = _groups(items, budget)
    # ``all``(48 参) 与 ``greedy_budget``(与 drop_biggest 同为 9 参) 只在
    # --full 下跑：前者数值雅可比极慢（配方正是为此设 40 护栏），后者是
    # 重复实验。默认只测「不精修 / 排除最大相 / 只精修最大相」三组。
    if "--full" not in argv:
        groups.pop("all", None)
        groups.pop("greedy_budget", None)
    ref = B._delta_baseline(pat, phases, b)
    print(f"增量基准 Rwp = {ref:.4f}（全部非线性关）\n", flush=True)

    mask = ((pat.two_theta >= cfg0.tmin) & (pat.two_theta <= cfg0.tmax))
    clip = replace(pat, two_theta=pat.two_theta[mask],
                   intensity=pat.intensity[mask])
    site_cfg = replace(cfg0, max_iter=min(int(cfg0.max_iter),
                                          XYZ_SITE_MAX_ITER))
    rows = B._read_json("s7_xyz.json")
    done = {r["group"] for r in rows if r.get("rwp_pct") is not None}

    for label, chosen in groups.items():
        if label in done:
            continue
        n_free = sum(n for j, (_s, _m, n) in enumerate(items) if j in chosen)
        if label not in ("none", "all") and not chosen:
            continue
        try:
            models = [items[j][1] for j in sorted(chosen) if items[j][1]]
            sources = [items[j][0] for j in sorted(chosen) if items[j][1]]
            fixed = [items[j][0] for j in range(len(items)) if j not in chosen]
            t0 = time.time()
            if models:
                sr = refine_sites(models, clip, b["prm"], site_cfg,
                                  backend="lm", free_kinds=("xyz",),
                                  fixed_structures=fixed)
            new_phases = []
            mi = 0
            for j, (st, m, _n) in enumerate(items):
                if j in chosen and m is not None:
                    st_new = sr.structures[mi]
                    for attr in META_ATTRS:
                        if hasattr(st, attr):
                            setattr(st_new, attr, getattr(st, attr))
                    new_phases.append(st_new)
                    mi += 1
                else:
                    new_phases.append(st)
            res = solve(RefineInputs(pat, new_phases, b["prm"], cfg0))
            row = {"group": label, "phases": [items[j][0].name
                                              for j in sorted(chosen)],
                   "n_free": n_free, "rwp_pct": float(res.rwp), "ref_rwp": ref,
                   "delta": float(res.rwp) - ref,
                   "seconds": round(time.time() - t0, 1)}
        except Exception as exc:                                  # noqa: BLE001
            row = {"group": label, "n_free": n_free, "rwp_pct": None,
                   "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1200:]}
        rows.append(row)
        B._write_json("s7_xyz.json", rows)
        print(json.dumps({k: row.get(k) for k in
                          ("group", "n_free", "rwp_pct", "delta", "seconds",
                           "error")}, ensure_ascii=False), flush=True)

    good = [r for r in rows if r.get("rwp_pct") is not None]
    if good:
        best = min(good, key=lambda r: r["rwp_pct"])
        print(f"\n当前最佳: {json.dumps(best, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
