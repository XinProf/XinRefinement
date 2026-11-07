"""向量化倒易点枚举与逐点循环版的数值等价性（v1.5 性能修复的护栏）。

背景：``compute_peaks`` 原来是 ``for h: for k: for l:`` 的三重 Python 循环，
对 IUCr 纯刚玉单次耗时 443 ms，占一次残差评估的 86%（cProfile 实测）。
改成 ``meshgrid`` 整体向量化后降到十几毫秒（26–37×），但**必须保证
峰位、强度、合并顺序、detail 明细全部不变**，否则所有既有 Rwp 结论都会
失效。这里把两套内核放在同一输入上逐项比对，任何一个数量级以上的偏差
都算回归。

覆盖矩阵：单色 / Cu Kα 双线、有/无 ``with_dirs``、March–Dollase r<1/r=1/r>1、
``po_detail``（逐 hkl 明细）、两个扫描窗口。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.profile.cif import parse_cif_string
from xinrefinement.core.profile.shape import resolve_wavelengths
from xinrefinement.core.profile import struct as S

CIFS = ("NCA_80_15_05.cif", "LiCoO2.cif", "AlOH3_gibbsite.cif")


def _load(cif_dir, name: str):
    path = cif_dir / name
    if not path.exists():
        pytest.skip(f"缺 {name}")
    return parse_cif_string(path.read_text(encoding="utf-8"), name.split(".")[0])


def _both(monkeypatch, struct, **kw):
    """同一输入分别走向量化与循环内核。"""
    monkeypatch.setattr(S, "_MAX_ENUM", 4_000_000)
    vec = S.compute_peaks(struct, **kw)
    monkeypatch.setattr(S, "_MAX_ENUM", 0)          # 0 -> 强制走 loop
    loop = S.compute_peaks(struct, **kw)
    return vec, loop


def _compare(tag: str, vec, loop) -> None:
    v_out, *v_rest = vec
    l_out, *l_rest = loop
    assert len(v_out) == len(l_out), f"{tag}: 峰数 {len(v_out)} vs {len(l_out)}"
    for a, b in zip(v_out, l_out):
        # 峰位：合并键容差 1e-3°，向量化只允许浮点末位差
        assert abs(a[0] - b[0]) < 1e-9, f"{tag}: 2θ {a[0]} vs {b[0]}"
        assert abs(a[1] - b[1]) <= 1e-12 * max(abs(b[1]), 1.0), \
            f"{tag}: 强度 {a[1]} vs {b[1]}"
        assert abs(a[2] - b[2]) < 1e-12, f"{tag}: d 值 {a[2]} vs {b[2]}"
        if len(a) > 3:
            assert a[3] == b[3], f"{tag}: 反射方向不同 {a[3]} vs {b[3]}"
    if v_rest and v_rest[0] is not None:
        d_vec, d_loop = v_rest[0], l_rest[0]
        assert len(d_vec) == len(d_loop), f"{tag}: detail 组数不同"
        for g1, g2 in zip(d_vec, d_loop):
            assert len(g1) == len(g2), f"{tag}: detail 组内条数不同"
            for (x1, y1), (x2, y2) in zip(g1, g2):
                assert abs(x1 - x2) <= 1e-12 * max(abs(x2), 1.0)
                assert abs(y1 - y2) < 1e-12


@pytest.mark.parametrize("name", CIFS)
def test_vec_matches_loop_basic(monkeypatch, cif_dir, name) -> None:
    st = _load(cif_dir, name)
    comps = resolve_wavelengths(1.5406, "Cu", 0.5)
    for tmin, tmax in ((5.0, 150.0), (10.0, 90.0)):
        vec, loop = _both(monkeypatch, st, wavelength=1.5406,
                          two_min=tmin, two_max=tmax, wavelengths=comps)
        _compare(f"{name} {tmin:g}-{tmax:g}", vec, loop)


@pytest.mark.parametrize("name", CIFS)
def test_vec_matches_loop_dirs_and_po(monkeypatch, cif_dir, name) -> None:
    st = _load(cif_dir, name)
    comps = resolve_wavelengths(1.5406, "Cu", 0.5)
    kw = dict(wavelength=1.5406, two_min=5.0, two_max=150.0,
              wavelengths=comps, with_dirs=True)
    vec, loop = _both(monkeypatch, st, **kw)
    _compare(f"{name} dirs", vec, loop)
    for r in (0.7, 1.0, 1.4):
        vec, loop = _both(monkeypatch, st, po=(0, 0, 1, r), **kw)
        _compare(f"{name} PO r={r}", vec, loop)
    vec, loop = _both(monkeypatch, st, po=(1, 0, 0, 1.0), po_detail=True, **kw)
    _compare(f"{name} PO detail", vec, loop)


def test_vec_is_faster(monkeypatch, cif_dir) -> None:
    """向量化版至少要比循环版快 5×（本机实测 26–37×，留足余量）。"""
    import time
    st = _load(cif_dir, "NCA_80_15_05.cif")
    comps = resolve_wavelengths(1.5406, "Cu", 0.5)
    kw = dict(wavelength=1.5406, two_min=5.0, two_max=150.0, wavelengths=comps)

    monkeypatch.setattr(S, "_MAX_ENUM", 4_000_000)
    t0 = time.perf_counter()
    S.compute_peaks(st, **kw)
    t_vec = time.perf_counter() - t0
    monkeypatch.setattr(S, "_MAX_ENUM", 0)
    t0 = time.perf_counter()
    S.compute_peaks(st, **kw)
    t_loop = time.perf_counter() - t0
    assert t_vec * 5 < t_loop, f"向量化 {t_vec*1e3:.0f}ms vs 循环 {t_loop*1e3:.0f}ms"


def test_huge_cell_falls_back_to_loop(monkeypatch, cif_dir) -> None:
    """超大晶胞（倒易点超上限）必须自动退回循环版而不是吃光内存。"""
    st = _load(cif_dir, "NCA_80_15_05.cif")
    monkeypatch.setattr(S, "_MAX_ENUM", 1)          # 任何晶胞都超限
    peaks, _skipped = S.compute_peaks(st, 1.5406, 10.0, 90.0)
    assert peaks and all(p[1] > 0 for p in peaks)
    assert np.all(np.diff([p[0] for p in peaks]) >= 0)
