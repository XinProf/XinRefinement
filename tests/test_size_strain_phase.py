"""v1.5 M8b：逐相**各向同性** TCH 尺寸/应变（MAUD ``Delft`` 口径）。

为什么需要它
------------
``ProfileParams.X``/``Y`` 是**全谱唯一标量**，而实测多相样的各相微结构可以
差 3 个量级——样 7 的 MAUD 模型里，石英 ``Delft`` 给 size 7586 Å、strain
4e-7（等于不展宽），方石英给 size 27.17 Å、strain 0.0164（21.9° 处 FWHM
约 3.3°，本质是个近非晶宽包）。单谱标量不可能同时表达这两者，此前的做法
是「所有相都开 6 参 Popa LB」，而 6 参张量在单谱上常常不可辨识：实测样 7
出现方石英某方向 FWHM 被撑到 1.87°、而实测只有 0.24°（4.8 倍过宽）。

逐相 2 参各向同性因此不只是「更贴 MAUD」，而是**给展宽加结构性约束**。

语义（与 ``aniso`` 的优先级）
----------------------------
前向取值顺序：``aniso`` 命中该相 → 用逐峰方向 (X, Y)；否则命中
``size_strain`` → 用该相 (X, Y)；否则用标量 ``X``/``Y``。
所以「方石英逐相宽包 + 其余相吃全局标量」可以并存。

精修开关 ``RefineConfig.refine_size_strain`` 默认 **False**：不开时注册表
不产生任何槽位，向量与边界逐位不变，golden 不漂；但 ``size_strain`` 里的
值仍作为**固定**展宽参与前向（与 ``aniso`` 只施加不精修的行为一致）。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.params.registry import build_registry_from_config
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.refine.nonlinear import (
    SIZE_BOUNDS,
    STRAIN_BOUNDS,
    RefineConfig,
)

from pathlib import Path

DATA = Path(__file__).parent.parent / "xinrefinement" / "data"


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]


def _base(**kw) -> ProfileParams:
    p = dict(U=0.02, V=0.0, W=0.02, eta=0.5, anode="Cu")
    p.update(kw)
    return ProfileParams(**p)


def test_phase_pair_equals_scalar_x_y(structs):
    """单相时逐相 (X, Y) 与标量 X/Y 逐位等价。"""
    grid = np.linspace(10.0, 90.0, 6001)
    st = structs[0]
    y_scalar = compute_phase_profile(
        st, grid, _base(X=0.12, Y=0.2), tmin=10.0, tmax=90.0)
    y_phase = compute_phase_profile(
        st, grid, _base(size_strain={st.name: (0.12, 0.2)}),
        tmin=10.0, tmax=90.0)
    assert np.allclose(y_scalar, y_phase, rtol=1e-9, atol=1e-9)


def test_phase_pair_only_affects_named_phase(structs):
    """只给一相加宽，另一相的计算谱必须逐位不变。"""
    grid = np.linspace(10.0, 90.0, 6001)
    a, b = structs
    prm_b0 = _base()
    prm_b1 = _base(size_strain={a.name: (0.0, 0.30)})
    y0 = compute_phase_profile(b, grid, prm_b0, tmin=10.0, tmax=90.0)
    y1 = compute_phase_profile(b, grid, prm_b1, tmin=10.0, tmax=90.0)
    assert np.array_equal(y0, y1)

    # 被点名的相必须真的变宽（峰高按积分归一化，宽则矮）
    ya0 = compute_phase_profile(a, grid, prm_b0, tmin=10.0, tmax=90.0)
    ya1 = compute_phase_profile(a, grid, prm_b1, tmin=10.0, tmax=90.0)
    assert ya1.max() < 0.9 * ya0.max()


def test_aniso_takes_precedence_over_phase_pair(structs):
    """同一相同时给 aniso 与 size_strain 时，aniso 优先（与文档一致）。"""
    from xinrefinement.core.profile.forward import aniso_default

    grid = np.linspace(10.0, 90.0, 6001)
    st = structs[0]
    iso = aniso_default(1.5406, x_deg=0.12, y_deg=0.2)
    y_aniso = compute_phase_profile(
        st, grid, _base(aniso={st.name: iso}), tmin=10.0, tmax=90.0)
    # 同时给一个**完全不同**的逐相值：结果应与纯 aniso 逐位相同
    y_both = compute_phase_profile(
        st, grid, _base(aniso={st.name: iso},
                        size_strain={st.name: (0.0, 0.45)}),
        tmin=10.0, tmax=90.0)
    assert np.array_equal(y_aniso, y_both)


def test_registry_slots_and_roundtrip(structs):
    """每个点名相产生 2 个槽位（X 应变 / Y 尺寸），pack→unpack 往返一致。"""
    a, b = structs
    prm = _base(size_strain={a.name: (0.01, 0.02), b.name: (0.03, 0.04)})
    cfg = RefineConfig(refine_zero=False, refine_uvw=False,
                       refine_size_strain=True)
    reg = build_registry_from_config(cfg, prm, n_phase=2)
    labels = reg.labels()
    assert labels == [
        f"phase[{a.name}].micro.X", f"phase[{a.name}].micro.Y",
        f"phase[{b.name}].micro.X", f"phase[{b.name}].micro.Y",
    ], labels
    x0 = reg.pack(prm, po_r=prm.po_r)
    assert np.allclose(x0, [0.01, 0.02, 0.03, 0.04])
    lo, hi = reg.bounds()
    assert lo[0] == STRAIN_BOUNDS[0] and hi[0] == STRAIN_BOUNDS[1]
    assert lo[1] == SIZE_BOUNDS[0] and hi[1] == SIZE_BOUNDS[1]

    prm2, _cell, _po = reg.unpack(x0 + 0.001, prm)
    assert prm2.size_strain[a.name] == pytest.approx((0.011, 0.021))
    assert prm2.size_strain[b.name] == pytest.approx((0.031, 0.041))


def test_flag_off_produces_no_slots_but_still_applies(structs):
    """默认关：注册表无槽位（零回归），但 size_strain 仍作为固定展宽生效。"""
    a = structs[0]
    prm = _base(size_strain={a.name: (0.0, 0.3)})
    reg = build_registry_from_config(
        RefineConfig(refine_zero=False, refine_uvw=False), prm, n_phase=1)
    assert reg.labels() == []
    assert reg.pack(prm, po_r=prm.po_r).size == 0

    grid = np.linspace(10.0, 90.0, 6001)
    assert not np.array_equal(
        compute_phase_profile(a, grid, prm, tmin=10.0, tmax=90.0),
        compute_phase_profile(a, grid, _base(), tmin=10.0, tmax=90.0))
