"""golden 活体校验：不依赖 XinMatch / COD 档案，任何环境都能跑。

为什么单独存在
--------------
`tests/test_joint_s1.py::test_s1_api_path_reproduces_golden_rwp` 是唯一断言
`tests/golden/method_b_roundtrip.json` 的用例，但它要先经过 XinMatch 导出
`.xinm`。2026-11-07 实测：本机缺 `gemmi`（XinMatch 的依赖）→ fixture 直接
`pytest.skip`，于是**整个 golden 校验从来没跑过**。后果是 `17525bb`
（M11 窗口边界峰外扩 + 结构因子向量化）把 8 档数值改了 1e-5~4.5e-3，而
golden 静默过期，一直没人发现。

本用例只走「仓库内虚拟谱 + 内置 TiO₂ CIF → `refine()`」，直接对拍 golden
的 50/50 档，成本约几秒，作为数值基线漂移的绊线。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
VIRTUAL_B = ROOT / "tests" / "data" / "virtual_b"
GOLDEN = ROOT / "tests" / "golden" / "method_b_roundtrip.json"

pytestmark = pytest.mark.skipif(
    not (VIRTUAL_B / "v50_wide.xy").is_file() or not GOLDEN.is_file(),
    reason="需要 virtual_b 虚拟谱与 golden 文件")


def _golden_5050() -> dict:
    rows = json.loads(GOLDEN.read_text(encoding="utf-8"))
    hit = [r for r in rows if abs(r["wa_true"] - 50.0) < 1e-9]
    assert hit, "golden 里没有 50/50 档"
    return hit[0]


def _load_xy(path: Path):
    xs, ys = [], []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        a, b = s.split()[:2]
        xs.append(float(a))
        ys.append(float(b))
    return np.array(xs), np.array(ys)


def test_golden_5050_bit_identical():
    from xinrefinement.core.dtypes import Pattern
    from xinrefinement.core.profile.cif import parse_cif
    from xinrefinement.core.profile.forward import ProfileParams
    from xinrefinement.core.refine.nonlinear import RefineConfig, refine

    g = _golden_5050()
    st_a = parse_cif(ROOT / "xinrefinement" / "data" / "anatase.cif")
    st_r = parse_cif(ROOT / "xinrefinement" / "data" / "rutile.cif")

    x, y = _load_xy(VIRTUAL_B / "v50_wide.xy")
    pat = Pattern(two_theta=x, intensity=y, meta={})
    prm0 = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                         anode="Cu", integrated=False)  # 合成数据=峰高口径
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False,
                       n_bg=3, max_iter=40, tmin=5.0, tmax=90.0)
    res = refine([st_a, st_r], pat, prm0, cfg)

    # 逐位口径：改任何数值路径都必须同时更新 golden，不许悄悄漂
    assert res.rf.rwp == pytest.approx(g["rwp"], rel=1e-12)
    assert res.params.zero == pytest.approx(g["zero"], rel=1e-12)
    assert res.params.U == pytest.approx(g["U"], rel=1e-12)
    assert res.params.V == pytest.approx(g["V"], rel=1e-12)
    assert res.params.W == pytest.approx(g["W"], rel=1e-12)
