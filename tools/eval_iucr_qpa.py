"""v1.5 外部验证：IUCr CPD 标准谱图的 Rietveld 定量准确度（QPA）。

为什么需要这个
--------------
到目前为止所有结论（M3/M4/M8/M9）都只在 ShiJiKong 7 个样上得出，容易被
质疑「只在这批数据上调参」。IUCr CPD 系列（``XRData/IUCr``）是国际晶体学
联合会组织的 round-robin 标准数据，**每个样都有称量真值 + XRF 复核**，
既可以看 Rwp，也可以直接算定量绝对误差，是本项目最该有的独立验证集。

数据与相
--------
- 谱图：``Must do/Rietveld/{1a,1b,1c,1g,2,3,4}.txt``，两列 (2θ, I)，
  5–150°、0.02° 步长、7251 点；λ = Cu Kα（CaF₂(111) 实测 28.28° 与
  1.5406 Å 吻合）
- 结构：刚玉取 `ShiJiKong3/4Entry_96-900-9673.cif`（COD，R-3c），
  ZnO / CaF₂ 取 IUCr 目录自带的 PDF 卡片 CIF
- **Mg(OH)₂ 的 CIF 只有 d 值与强度、没有原子坐标**（PDF 卡片导出），
  故 Sample 2 暂缺该相；Sample 4 需 Fe₃O₄/ZrSiO₄，本地未找到结构 CIF。
  两者都在 ``MISSING`` 里显式记录，不静默降级。

用法::

    python tools/eval_iucr_qpa.py --samples 1g
    python tools/eval_iucr_qpa.py --samples 1a,1b,1c,1g
    python tools/eval_iucr_qpa.py --report

输出 ``C:\\Temp\\iucr\\qpa.json``（临时数据，不入 Git）。
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xinrefinement.core.patterns import load_pattern            # noqa: E402
from xinrefinement.core.profile.cif import parse_cif            # noqa: E402
from xinrefinement.core.profile.forward import ProfileParams    # noqa: E402
from xinrefinement.core.refine.nonlinear import RefineConfig    # noqa: E402
from xinrefinement.core.refine.recipe import RecipeRunner       # noqa: E402
from xinrefinement.core.refine.solve import RefineInputs        # noqa: E402

ROOT = Path(r"D:\Project\XRD\XRData\IUCr\Must do\Rietveld")
OUT = Path(r"C:/Temp/iucr")
OUT.mkdir(parents=True, exist_ok=True)

#: 结构 CIF（刚玉取 ShiJiKong3 的 COD 文件，ZnO/CaF₂ 取 IUCr 自带）
CIF = {
    "Corundum": Path(r"D:\Project\XRDdata\ShiJK-Refinement"
                     r"\ShiJiKong3#1##20260126-130900_100"
                     r"\4Entry_96-900-9673.cif"),
    "Zincite": ROOT / "Entry_96-230-0113-ZnO.cif",
    "Fluorite": ROOT / "Entry_96-230-0450-CaF2.cif",
}

#: Sample 2/3/4 的另一半结构本地没有，按 COD 编号下载（缓存到 ``OUT/cif``）。
#: 记编号而不仅是路径，是为了可复现——IUCr 目录只给了 Sample 1 的 CIF。
#: 注意 COD 里 ``1000054`` 是 Brucite、``1011032`` 是 Magnetite（经典
#: "The Structure of Magnetite and the Spinels"）、``5000119`` 是 Zircon；
#: 别用 ``1011035``/``1000055``（那是长石和 LaB₆，纯属编号猜错）。
COD = {
    "Brucite": ("1000054", "brucite.cif"),
    "Magnetite": ("1011032", "magnetite.cif"),
    "Zircon": ("5000119", "zircon.cif"),
}


def _cod_fetch(cid: str, fn: str) -> Path:
    """按 COD 编号取 CIF（首次下载后缓存）。

    ``curl`` 在本机对 crystallography.net 会 exit 56；``urllib`` 通常可以，
    但偶发 ``SSL: UNEXPECTED_EOF_WHILE_READING``，故做 3 次退避重试。
    缓存目录是 ``OUT/cif``——手工把 CIF 放进去也能直接用，不必联网。
    """
    p = OUT / "cif" / fn
    if p.exists():
        return p
    import ssl
    import time as _time
    import urllib.request
    ctx = ssl._create_unverified_context()
    url = f"https://www.crystallography.net/cod/{cid}.cif"
    last: Exception | None = None
    for attempt in range(3):
        try:
            data = urllib.request.urlopen(url, timeout=60, context=ctx).read()
            if not data:
                raise RuntimeError("空响应")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            return p
        except Exception as exc:                              # noqa: BLE001
            last = exc
            _time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(
        f"COD {cid} 下载失败（{type(last).__name__}: {last}）。"
        f"可手工下载 https://www.crystallography.net/cod/{cid}.cif "
        f"存为 {p} 后重跑")


def _cif_path(name: str) -> Path:
    if name in CIF:
        return CIF[name]
    cid, fn = COD[name]
    return _cod_fetch(cid, fn)


#: 称量真值（wt%，见 IUCr物相说明-en.txt）与 XRF 复核值。
#: Sample 1 一共 8 个配比点（1a–1h），全部有称量真值，全部纳入评估——
#: 只有 8 个点 × 3 相 = 24 个 wt% 数据才谈得上「定量准确度」统计。
TRUTH = {
    "1a": {"Corundum": 1.15, "Zincite": 4.04, "Fluorite": 94.81},
    "1b": {"Corundum": 94.31, "Zincite": 1.36, "Fluorite": 4.33},
    "1c": {"Corundum": 5.04, "Zincite": 93.59, "Fluorite": 1.36},
    "1d": {"Corundum": 13.53, "Zincite": 32.89, "Fluorite": 53.58},
    "1e": {"Corundum": 55.12, "Zincite": 15.25, "Fluorite": 29.62},
    "1f": {"Corundum": 27.06, "Zincite": 55.22, "Fluorite": 17.72},
    "1g": {"Corundum": 31.37, "Zincite": 34.21, "Fluorite": 34.42},
    "1h": {"Corundum": 35.12, "Zincite": 30.19, "Fluorite": 34.69},
    # Sample 2 = 择优取向专项（ZnO 针状习性 + 层状 Brucite）
    "2": {"Corundum": 21.27, "Zincite": 19.94, "Fluorite": 22.53,
          "Brucite": 36.26},
    # Sample 3 = 含 29.47 wt% 非晶玻璃 → 我们没有非晶模型，只精修 3 个晶相，
    # 结果会自动归一化到「晶相合计 70.53」，故用 ``TRUTH_CRYST`` 口径比对
    "3": {"Corundum": 30.79, "Zincite": 19.68, "Fluorite": 20.06},
    # Sample 4 = 微吸收专项（Fe₃O₄ μ 极大，与刚玉对比使微吸收必须建模）
    "4": {"Corundum": 50.46, "Magnetite": 19.64, "Zircon": 29.90},
}

#: 玻璃相含量（wt%），用于把 Sample 3 的真值重归一化到晶相口径
AMORPHOUS = {"3": 29.47}


def truth_cryst(tag: str) -> dict:
    """真值重归一化到「参与精修的晶相」口径（目前只影响 Sample 3）。

    Sample 3 含 29.47 wt% 非晶玻璃而我们**没有非晶模型**，精修出来的
    wt% 会在 3 个晶相之间归一化到 100。故公平的比对基准是
    ``truth × 100 / Σtruth``，而不是原 truth——
    否则 47.3 会被拿去和 30.79 比，凭空多出 16.5 pt 的「误差」。
    """
    t = TRUTH[tag]
    amor = AMORPHOUS.get(tag, 0.0)
    if amor <= 0:
        return dict(t)
    total = sum(t.values())
    if total <= 0:
        return dict(t)
    scale = 100.0 / total
    return {k: v * scale for k, v in t.items()}


#: XRF 复核值（同上表），用来区分「称量误差」与「模型误差」
XRF = {
    "1a": {"Corundum": 1.22, "Zincite": 4.12, "Fluorite": 94.11},
    "1b": {"Corundum": 94.73, "Zincite": 1.38, "Fluorite": 4.32},
    "1c": {"Corundum": 5.12, "Zincite": 93.15, "Fluorite": 1.33},
    "1d": {"Corundum": 13.80, "Zincite": 32.98, "Fluorite": 52.99},
    "1e": {"Corundum": 55.79, "Zincite": 15.34, "Fluorite": 29.39},
    "1f": {"Corundum": 27.32, "Zincite": 54.88, "Fluorite": 17.44},
    "1g": {"Corundum": 31.70, "Zincite": 34.01, "Fluorite": 33.86},
    "1h": {"Corundum": 35.35, "Zincite": 30.03, "Fluorite": 34.26},
    "2": {"Corundum": 20.94, "Zincite": 19.49, "Fluorite": 24.14,
          "Brucite": 36.14},
    "3": {"Corundum": 31.06, "Zincite": 19.64, "Fluorite": 19.89},
    "4": {"Corundum": 50.36, "Magnetite": 19.56, "Zircon": 29.51},
}

#: 各谱用哪些相（顺序会被按 CIF 文件名排序后的实际相顺序覆盖，仅作声明）
PHASES = {tag: tuple(TRUTH[tag]) for tag in TRUTH}

#: 谱图文件解析。``Must do/Rietveld`` 里的 1a/1b/1c/1g 与 ``txt`` 目录的
#: ``*_raw`` 逐字节相同（md5 已核对），1d/1e/1f/1h 只在 ``txt`` 目录里有，
#: 故按 tag 回退查找。**只用 _raw，不用 _mdi**（mdi 是另一次测量/整理版本，
#: 与 Rietveld 目录口径不一致）。
TXT = Path(r"D:\Project\XRD\XRData\IUCr\txt")


def _pattern_path(tag: str) -> Path:
    p = ROOT / f"{tag}.txt"
    if p.exists():
        return p
    for name in (f"CPD-{tag.upper()}_raw.txt", f"CPD-{tag.upper()}.txt"):
        q = TXT / name
        if q.exists():
            return q
    raise FileNotFoundError(f"{tag}: 谱图未找到")

#: 明确无法建模、因此**跳过**的样品（不静默跳过）。Sample 2/4 的结构已按
#: COD 补齐，8 个 Sample-1 点也齐，故目前为空。
#: Sample 3 仍会跑，但它含 29.47 wt% 非晶玻璃而我们没有非晶模型——真值按
#: 晶相重归一化后比对（``truth_cryst``），偏差里含玻璃的系统影响，解读时
#: 必须扣掉这一层。
MISSING: dict[str, str] = {}

T_MIN, T_MAX = 5.0, 150.0


def _prm(microabs: dict | None = None) -> ProfileParams:
    return ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=True,
                         microabs=microabs or None)


def _microabs_for(phases, grain: float) -> dict:
    """按统一晶粒半径估算每相 Brindley μ·r（``core.absorption`` 同一实现）。

    Sample 4 是 IUCr 的微吸收专项：磁铁矿 μ=1180 cm⁻¹、刚玉只有 126，
    相差近 10 倍，μ·r 只能靠化学成分算，不能靠精修（与每相 scale 简并）。
    """
    from xinrefinement.core.absorption import calc_microabs
    return calc_microabs(phases, {st.name: float(grain) for st in phases},
                         anode="Cu")


def _cfg(combo: bool, asym: bool = False, biso: bool = True) -> RefineConfig:
    n_bg = max(6, int(round((T_MAX - T_MIN) / 8.0)))
    kw = dict(n_bg=n_bg, bg_mode="tent", tmin=T_MIN, tmax=T_MAX, max_iter=40,
              weight_mode="sqrt")
    #: MAUD 的 ``_riet_asymmetry_tan_dep`` 是全局开的，而我们的
    #: ``refine_asym`` 为保持 golden 默认关。IUCr 数据从 5° 起，低角
    #: 不对称尾很明显，故评估里可显式打开做口径对齐。
    if asym:
        kw["refine_asym"] = True
    if combo:
        kw.update(po_probe=True, refine_biso=biso, refine_xyz=True,
                  refine_aniso=True, aniso_auto=True, refine_eta=True,
                  xyz_phase_select="largest")
    return RefineConfig(**kw)


def _weights(res) -> dict:
    return {p.name: (None if p.weight_pct is None
                     else float(p.weight_pct)) for p in res.phases}


def _match(weights: dict, truth: dict) -> dict:
    """把精修相名与真值相名配对（相名是 CIF 名，用元素/关键词匹配）。"""
    # 顺序有讲究：先判 Brucite（含 "h" 与 "mg"）再判 Zincite，
    # 且 ``Zircon`` 不能被 "zinc" 命中——"zircon" 里没有 "zinc"，安全。
    keys = {"Brucite": ("brucite", "mg(oh", "mgoh", "mg_h"),
            "Corundum": ("corund", "al2", "9673"),
            "Fluorite": ("caf", "fluor"),
            "Magnetite": ("magnetit", "fe3o4"),
            "Zircon": ("zircon",),          # 注意：不是 "zinc"
            "Zincite": ("zno", "zincite", "zinc_")}
    out: dict[str, float | None] = {}
    for phase, wt in weights.items():
        low = phase.lower()
        for name, pats in keys.items():
            if name not in truth:
                continue
            if any(p in low for p in pats):
                out[name] = wt
                break
    return out


def run_one(tag: str, combo: bool, rows: list, asym: bool = False,
            biso: bool = True, out: str = "qpa.json",
            grain: float = 0.0) -> None:
    mode = ("combo" if combo else "base") + ("+asym" if asym else "")
    if not biso:
        mode += "-biso"
    if grain:
        mode += f"+ma{grain:g}"
    if any(r.get("tag") == tag and r.get("mode") == mode
           and r.get("rwp_pct") is not None for r in rows):
        return
    try:
        pat = load_pattern(_pattern_path(tag))
        phases = [parse_cif(_cif_path(n)) for n in PHASES[tag]]
        ma = _microabs_for(phases, grain) if grain else None
        t0 = time.time()
        res, recs = RecipeRunner().run_all(
            RefineInputs(pat, phases, _prm(ma), _cfg(combo, asym, biso)))
        if res is None:
            raise RuntimeError("配方无结果")
        truth = truth_cryst(tag)
        w = _weights(res)
        got = _match(w, truth)
        err = {k: (None if got.get(k) is None
                   else round(got[k] - truth[k], 2)) for k in truth}
        #: 逐相 B_iso 是诊断定量偏差的关键：Rietveld 里 scale factor 与
        #: B_iso 强相关（IUCr round-robin 明确点出），某相 B 被推大就会
        #: 系统性压低它的 wt%。
        biso_map: dict[str, float] = {}
        for k, v in (res.params.b_iso or {}).items():
            try:
                biso_map[k] = round(float(v), 3)
            except (TypeError, ValueError):
                continue
        row = {"tag": tag, "mode": mode, "rwp_pct": float(res.rwp),
               "seconds": round(time.time() - t0, 1),
               "weights": {k: None if v is None else round(v, 2)
                           for k, v in w.items()},
               "matched": got, "truth": truth, "error_pt": err,
               "max_abs_err": (None if any(v is None for v in err.values())
                               else max(abs(v) for v in err.values())),
               "b_iso": biso_map,
               "biso_hit": sorted(k for k, v in biso_map.items() if v >= 5.99),
               "steps": [(r.key, r.status,
                          None if r.rwp_after is None else round(r.rwp_after, 3),
                          r.message[:80]) for r in recs]}
    except Exception as exc:                                      # noqa: BLE001
        row = {"tag": tag, "mode": mode, "rwp_pct": None,
               "error": f"{type(exc).__name__}: {exc}",
               "trace": traceback.format_exc()[-1000:]}
    rows.append(row)
    (OUT / out).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: row.get(k) for k in
                      ("tag", "mode", "rwp_pct", "max_abs_err",
                       "matched", "error_pt", "b_iso", "seconds", "error")},
                     ensure_ascii=False), flush=True)


def report(rows: list) -> None:
    modes = sorted({r.get("mode") for r in rows if r.get("rwp_pct")})
    order = ("1a", "1b", "1c", "1d", "1e", "1f", "1g", "1h", "2", "3", "4")
    seen: set[str] = set()
    for r in rows:
        if r.get("rwp_pct"):
            seen.update(r.get("truth") or {})
    phases = [p for p in ("Corundum", "Zincite", "Fluorite", "Brucite",
                          "Magnetite", "Zircon") if p in seen]
    head = " | ".join(f"{p} 实测/真值" for p in phases)
    print(f"\n| 样品 | 模式 | Rwp% | {head} | 最大偏差 |")
    print("|---|---|---:|" + "---|" * len(phases) + "---:|")
    for tag in order:
        for mode in modes:
            r = next((x for x in rows if x.get("tag") == tag
                      and x.get("mode") == mode and x.get("rwp_pct")), None)
            if r is None:
                continue
            cells = []
            for name in phases:
                g = (r.get("matched") or {}).get(name)
                t = (r.get("truth") or {}).get(name)
                if t is None:
                    cells.append("—")
                else:
                    cells.append("—" if g is None else f"{g:.2f} / {t:.2f}")
            print(f"| {tag} | {mode} | {r['rwp_pct']:.3f} | "
                  + " | ".join(cells) + f" | {r.get('max_abs_err')} |")
    ok = [r for r in rows if r.get("max_abs_err") is not None]
    if ok:
        best = min(ok, key=lambda r: r["max_abs_err"])
        print(f"\n最小定量偏差: {best['tag']} {best['mode']} "
              f"max|Δ| = {best['max_abs_err']} pt (Rwp {best['rwp_pct']:.3f})")
        for mode in modes:
            sel = [r for r in ok if r.get("mode") == mode]
            if sel:
                mae = sum(r["max_abs_err"] for r in sel) / len(sel)
                rw = sum(r["rwp_pct"] for r in sel) / len(sel)
                print(f"  {mode}: n={len(sel)} 平均 max|Δ| = {mae:.2f} pt，"
                      f"平均 Rwp = {rw:.3f}%")
        print("\nSample 3 含 29.47 wt% 非晶玻璃，真值已按晶相重归一化；"
              "其偏差含「无玻璃模型」的系统影响。")


def main(argv: list[str]) -> int:
    out = "qpa.json"
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    rows_path = OUT / out
    rows = (json.loads(rows_path.read_text(encoding="utf-8"))
            if rows_path.exists() else [])
    if "--report" in argv:
        report(rows)
        return 0
    sel = "1g"
    for i, a in enumerate(argv):
        if a == "--samples" and i + 1 < len(argv):
            sel = argv[i + 1]
    asym = "--asym" in argv
    biso = "--no-biso" not in argv
    grain = 0.0
    for i, a in enumerate(argv):
        if a == "--grain" and i + 1 < len(argv):
            grain = float(argv[i + 1])
    #: ``--only combo`` / ``--only base`` 可只跑一个口径，便于做单项对照
    only = ""
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = argv[i + 1].strip().lower()
    for tag in [s.strip() for s in sel.split(",") if s.strip()]:
        if tag in MISSING:
            print(f"[跳过] {tag}: {MISSING[tag]}", flush=True)
            continue
        for combo in (False, True):
            if only and only != ("combo" if combo else "base"):
                continue
            run_one(tag, combo, rows, asym, biso, out, grain)
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
