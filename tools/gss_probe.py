"""用本机 GSAS-II（``C:\\gsas2main``）解析 IUCr CPD 的 ``.gss`` 文件，
并与 ``txt/CPD-*.txt`` 的同名谱逐点比对。

为什么需要这个工具
------------------
``.gss`` 是 **GSAS 老版的 ASCII 粉末数据文件**（不是二进制工程文件），
GSAS-II 的 ``GSASII/imports/G2pwd_fxye.py`` 明确把它列进
``extensionlist``（``.fxye/.raw/.gsas/.gda/.gsa/.gss/.dat/XRA``）。
文件结构三段：

    SampleIdent CPD RR S
    BANK    1       7251       726 CONST        500.00      2.00     0.000     0.000
     1   166 1   169 ...            每行 10 组 8 字符记录

``BANK`` 行字段含义（``GSAS_ReaderClass`` 的 ``GetSTDdata`` 口径）：
``cons[2]`` = 点数 Nch，``cons[3]`` = 记录行数，
``cons[5]`` = 起始 2θ×100（centidegree）→ 5.00°，``cons[6]`` = 步长×100 → 0.02°。
每 8 字符记录里前 2 字符是每点计数 ``n``、后 6 字符是强度 ``y``，
而 **权重取 ``w = 1/(y/n)``**（``vi = yi/ni``，即 ``σ² = y/n``）——
``n ≡ 1`` 时就是 Poisson 权重 ``σ² = y``，与我们
``RefineConfig(weight_mode="sqrt")`` 的口径同源。

GSAS-II 的 off-by-one（必须记住）
--------------------------------
``GetSTDdata`` 里写的是

    j += 1
    if j < Nch:
        x.append(xi)

``j`` **先自增再判界**，末点自增后 ``j == Nch``，``j < Nch`` 为假 →
**STD 格式 bank 的最后一个数据点在 GSAS-II 里恒定丢失**。
CPD-4 因此读出 7250 点、止于 149.98°，而文件里确有 7251 点、止于 150.00°。
本工具会把这一点直接从文件末行补回来并标注，不做静默丢弃。

因此 ``.gss`` 相对 ``txt`` 的价值在于：**它自带起始角/步长/计数记录**，
可以核对 ``txt`` 的 x 轴口径，并在需要时用 ``n`` 构造
``σ² = y/n`` 的实验权重，不必假设 ``σ² = y``。

用法
----
    C:\\gsas2main\\python.exe tools/gss_probe.py                 # 全部核对
    C:\\gsas2main\\python.exe tools/gss_probe.py cpd-4 cpd-1g    # 指定若干

退出码 0 = 全部一致；1 = 有不一致（会列出第一处差异点）。
"""

from __future__ import annotations

import sys
from pathlib import Path

GSAS2 = Path(r"C:\gsas2main\GSAS-II")
GSAS = Path(r"D:\Project\XRD\XRData\IUCr\gsas")
TXT = Path(r"D:\Project\XRD\XRData\IUCr\txt")

#: ``.gss`` 名 → ``txt`` 名。``txt`` 里 1a–1e 与 2/3 只有 ``_raw`` 版本，
#: 1f/1g/1h/4 只有无后缀版本，bauxite/granodio 只有 ``_raw``——实测都同源。
TXT_MAP = {
    "cpd-1a": "CPD-1A_raw.txt",
    "cpd-1b": "CPD-1B_raw.txt",
    "cpd-1c": "CPD-1C_raw.txt",
    "cpd-1d": "CPD-1D_raw.txt",
    "cpd-1e": "CPD-1E_raw.txt",
    "cpd-1f": "CPD-1F.txt",
    "cpd-1g": "CPD-1G.txt",
    "cpd-1h": "CPD-1H.txt",
    "cpd-2": "CPD-2_raw.txt",
    "cpd-3": "CPD-3_raw.txt",
    "cpd-4": "CPD-4.txt",
    "cpd-y2o3": "CPD-Y2O3.txt",
    "bauxite": "BAUXITE_raw.txt",
    "granodio": "GRANODIO_raw.txt",
    "brucite": "BRUCITE.txt",
    "corundum": "CORUNDUM.txt",
    "fluorite": "FLUORITE.txt",
    "magnetit": "MAGNETIT.txt",
    "silica": "SILICA.txt",
    "zincite": "ZINCITE.txt",
    "zircon": "ZIRCON.txt",
    "mannitol": "MANNITOL.txt",
    "nizatidi": "NIZATIDI.txt",
    "pharm1gr": "PHARM1GR.txt",
    "pharm2gr": "PHARM2GR.txt",
    "starch": "STARCH.txt",
    "sucrose": "SUCROSE.txt",
    "valine": "VALINE.txt",
}


def _reader():
    """构造 GSAS-II 的 GSAS powder 读取器。

    ``C:\\gsas2main\\python.exe`` 的默认 ``sys.path`` **不含** ``GSAS-II``
    目录（它只装了依赖，没装包），必须先手工插进去才能 ``import GSASII``。
    """
    if str(GSAS2) not in sys.path:
        sys.path.insert(0, str(GSAS2))
    from GSASII.imports import G2pwd_fxye

    return G2pwd_fxye.GSAS_ReaderClass()


def _bank_nch(path: Path) -> int:
    """从 ``BANK`` 行取声明的点数 ``Nch``（``cons[2]``）。"""
    for line in path.read_text(encoding="latin-1").splitlines()[:4]:
        if line.startswith("BANK"):
            return int(line.split()[2])
    raise RuntimeError(f"{path.name}: 无 BANK 行")


def _tail_record(path: Path) -> tuple[int, int]:
    """直接解析文件最后一个 8 字符记录，返回 ``(n, y)``。

    用于补回 GSAS-II 因 ``j < Nch`` off-by-one 丢掉的末点。
    从最后一个 ``BANK`` 之后的所有数据行里取最后一行的第一条记录。
    """
    lines = path.read_text(encoding="latin-1").splitlines()
    last = None
    for line in lines:
        if line.startswith("BANK"):
            last = None
            continue
        if line.startswith("#"):
            continue
        if line[:10].strip():
            last = line
    if last is None:
        raise RuntimeError(f"{path.name}: 找不到数据行")
    return int(last[0:2]), int(last[2:8])


def read_gss(path: Path):
    """返回 ``(x, y, w, y_over_n)``。

    ``w`` 用 GSAS-II 自己算的 ``1/(y/n)``；``y_over_n`` 由 ``1/w`` 反推，
    供核对 ``σ² = y/n``（``n ≡ 1`` 时即 ``σ² = y``）。
    ``y == 0`` 的点 GSAS-II 把 ``w`` 置 0，反推不出比值，标 ``nan``。
    """
    import numpy as np

    rd = _reader()
    rd.selections = []
    if not rd.ContentsValidator(str(path)):
        raise RuntimeError(f"{path.name}: {rd.errors}")
    rd.selections = []
    rd.Reader(str(path))
    x, y, w = rd.powderdata[0], rd.powderdata[1], rd.powderdata[2]
    w = np.asarray(w, dtype=float)
    ok = w > 0
    ratio = np.full(len(w), np.nan, dtype=float)
    ratio[ok] = 1.0 / w[ok]
    return np.asarray(x, float), np.asarray(y, float), w, ratio


def read_txt(path: Path):
    xs, ys = [], []
    for line in path.read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    return xs, ys


def check(name: str, verbose: bool = True) -> tuple[bool, list[str]]:
    """核对单个 ``.gss``；返回 (是否一致, 说明行列表)。"""
    msgs: list[str] = []
    gss = GSAS / f"{name}.gss"
    if not gss.exists():
        return False, [f"{name}: 缺 .gss"]
    x, y, _, ratio = read_gss(gss)

    nch = _bank_nch(gss)
    n_got = len(x)
    step = float((x[-1] - x[0]) / (n_got - 1)) if n_got > 1 else float("nan")
    dropped = n_got == nch - 1

    head = (f"{name:10s} Nch={nch:5d} 读到={n_got:5d} "
            f"2θ={x[0]:7.3f}–{x[-1]:8.3f} step={step:.4f} Σy={y.sum():10.0f}"
            + ("  [GSAS-II 丢末点]" if dropped else ""))
    ok = True

    txt_name = TXT_MAP.get(name)
    if txt_name is None:
        msgs.append(head + "  （无 txt 对照）")
        return True, msgs
    tp = TXT / txt_name
    if not tp.exists():
        msgs.append(head + f"  （缺 {txt_name}）")
        return False, msgs

    tx, ty = read_txt(tp)
    if len(tx) != nch:
        msgs.append(head + f"  ✗ txt 点数 {len(tx)} ≠ Nch {nch}")
        return False, msgs

    # x 逐点（txt 写 5.000 保留 3 位，容差 1e-3；GSAS-II 走 start+step*j 累加）
    dx = max(abs(a - b) for a, b in zip(x, tx[:n_got]))
    d = [int(round(ty[i])) - int(round(y[i])) for i in range(n_got)]
    dy_bad = [i for i in range(n_got) if d[i] != 0]

    # 末点：GSAS-II 丢了就从文件末行补回，再和 txt 末点比
    tail_note = ""
    tail_d = 0
    if dropped:
        n_cnt, y_tail = _tail_record(gss)
        want = int(round(ty[-1]))
        tail_d = y_tail - want
        if tail_d == 0:
            tail_note = f"  末点({nch-1}) 补回 y={y_tail}=txt ✓ n={n_cnt}"
        elif abs(tail_d) == 1:
            tail_note = f"  末点({nch-1}) 补回 y={y_tail}，txt {want}（舍入差）"
        else:
            ok = False
            tail_note = f"  ✗ 末点补回 y={y_tail} ≠ txt {want}"

    if dx <= 6e-4 and not dy_bad and tail_d == 0:
        # σ² = y/n 是否退化为 σ² = y（即全部 n ≡ 1）
        good = ratio[ratio == ratio]
        poisson = bool(good.size and (abs(good - y[ratio == ratio]) < 0.5).all())
        tail = "  n≡1→σ²=y" if poisson else f"  n≠1(均值 {good.mean():.2f})"
        msgs.append(head + f"  ✓ dx={dx:.1e} y 全同 {txt_name}{tail}{tail_note}")
        return True, msgs

    # 舍入差：|Δy| ≤ 1、单向、且不到六成点 → 判为两路导出舍入口径差
    if dx <= 6e-4 and set(d) <= {0, -1} and len(dy_bad) < 0.6 * n_got:
        frac = 100.0 * len(dy_bad) / n_got
        msgs.append(head + f"  ~ dx={dx:.1e} y 舍入差≤1 于 {frac:.0f}% 点 "
                           f"（gss=txt+1，与强度无关）{txt_name}{tail_note}")
        return True, msgs

    ok = False
    msg = head + f"  ✗ dx={dx:.2e} y 差 {len(dy_bad)}/{n_got} 点"
    if dy_bad:
        i = dy_bad[0]
        msg += f"  首位 i={i} 2θ={x[i]:.2f} gss={y[i]:.0f} txt={ty[i]:.0f}"
    msgs.append(msg + tail_note)
    return ok, msgs



def main(argv: list[str]) -> int:
    names = argv[1:] or sorted(p.stem for p in GSAS.glob("*.gss"))
    bad = 0
    for name in names:
        ok, msgs = check(name.lower())
        for m in msgs:
            print(m)
        bad += 0 if ok else 1
    print(f"\n{len(names) - bad}/{len(names)} 一致")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
