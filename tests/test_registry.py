"""P1.0b · ParameterRegistry 双轨逐位一致性验收。

核心判据：registry 的 pack/unpack/bounds 必须与 ``nonlinear._pack/_unpack/
_bounds`` **逐位一致**（P1.0c 才能安全替换旧路径）。覆盖多种开关组合、
cell、PO、X/Y 单独开与同时开。
"""
from __future__ import annotations

import numpy as np
import pytest

from xinrefinement.core.params.registry import (
    ParameterRegistry,
    build_registry_from_config,
)
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine import nonlinear as nl

_FLAG_KEYS = ("refine_zero", "refine_uvw", "refine_eta", "refine_asym",
              "refine_bfactor", "refine_cell", "refine_po", "refine_strain",
              "refine_size")


def _configs():
    base = dict.fromkeys(_FLAG_KEYS, False)
    yield nl.RefineConfig(**base)
    yield nl.RefineConfig(**dict.fromkeys(_FLAG_KEYS, True))
    for k in _FLAG_KEYS:
        yield nl.RefineConfig(**{**base, k: True})
    for a, b in (("refine_cell", "refine_po"), ("refine_strain", "refine_size"),
                 ("refine_po", "refine_size"), ("refine_po", "refine_strain"),
                 ("refine_cell", "refine_size")):
        d = dict(base)
        d[a] = d[b] = True
        yield nl.RefineConfig(**d)


def _cfg_id(cfg) -> str:
    return "".join(k.split("refine_")[1][0] for k in _FLAG_KEYS
                   if getattr(cfg, k)) or "none"


CONFIGS = list(_configs())
IDS = [_cfg_id(c) for c in CONFIGS]


@pytest.mark.parametrize("cfg", CONFIGS, ids=IDS)
def test_pack_matches_legacy(cfg):
    prm = ProfileParams(
        zero=0.031, U=0.021, V=-0.013, W=0.018, eta=0.62,
        asym=0.07, bfactor=0.31, X=0.023, Y=0.037, anode="Cu",
        po_r={"anatase": (0, 0, 1, 1.12), "rutile": (1, 1, 0, 0.93)},
    )
    n_phase = 2
    reg = build_registry_from_config(cfg, prm, n_phase=n_phase,
                                     po_names=sorted(prm.po_r))
    # 两边统一用「默认全 1 cell + 同一 po_r」作为输入
    old = nl._pack(prm, cfg, n_phase)
    new = reg.pack(prm, po_r=prm.po_r)
    assert new.shape == old.shape, (reg.labels(), old)
    assert np.array_equal(new, old), (reg.labels(), new, old)


@pytest.mark.parametrize("cfg", CONFIGS, ids=IDS)
def test_bounds_match_legacy(cfg):
    prm = ProfileParams(po_r={"anatase": (0, 0, 1, 1.0)})
    n_phase = 2
    n_po = len(prm.po_r) if cfg.refine_po else 0
    reg = build_registry_from_config(cfg, prm, n_phase=n_phase,
                                     po_names=sorted(prm.po_r))
    lo_old, hi_old = nl._bounds(cfg, n_phase, n_po)
    lo_new, hi_new = reg.bounds()
    assert np.array_equal(lo_new, lo_old)
    assert np.array_equal(hi_new, hi_old)
    assert lo_new.size == hi_new.size == reg.size


@pytest.mark.parametrize("cfg", CONFIGS, ids=IDS)
def test_unpack_matches_legacy(cfg):
    base = ProfileParams(
        zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5, asym=0.0, bfactor=0.0,
        X=0.0, Y=0.0, anode="Cu", integrated=True,
        po_r={"anatase": (0, 0, 1, 1.0), "rutile": (1, 1, 0, 1.0)},
    )
    n_phase = 2
    po_names = sorted(base.po_r)
    reg = build_registry_from_config(cfg, base, n_phase=n_phase,
                                     po_names=po_names)
    x = nl._pack(base, cfg, n_phase)
    x = x + np.linspace(0.001, 0.002, max(x.size, 1))[:x.size]

    old_prm, old_cell = nl._unpack(x, base, cfg, n_phase)
    new_prm, new_cell, new_po = reg.unpack(x, base, po_r=base.po_r)

    for f in ("zero", "U", "V", "W", "eta", "asym", "bfactor", "X", "Y"):
        assert getattr(new_prm, f) == pytest.approx(getattr(old_prm, f)), f
    assert new_cell == old_cell
    if cfg.refine_po:
        for name in po_names:
            assert new_po[name] == pytest.approx(old_prm.po_r[name]), name


def test_full_flags_roundtrip_preserves_values():
    """全开关：pack→unpack 应原样还原（含 cell / PO / X/Y 倒读）。"""
    cfg = nl.RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                          refine_asym=True, refine_bfactor=True,
                          refine_cell=True, refine_po=True,
                          refine_strain=True, refine_size=True)
    prm = ProfileParams(zero=0.02, U=0.03, V=-0.01, W=0.02, eta=0.6,
                        asym=0.05, bfactor=0.3, X=0.02, Y=0.03,
                        po_r={"b": (1, 1, 0, 0.9), "a": (0, 0, 1, 1.1)})
    cell = [(1.005, 0.998), (0.997, 1.004)]
    reg = build_registry_from_config(cfg, prm, 2, sorted(prm.po_r))
    x = reg.pack(prm, cell_scales=cell, po_r=prm.po_r)
    out, cell_out, po_out = reg.unpack(x, prm, cell_scales=cell, po_r=prm.po_r)
    assert out.X == pytest.approx(0.02) and out.Y == pytest.approx(0.03)
    assert cell_out == [(1.005, 0.998), (0.997, 1.004)]
    assert po_out["a"][3] == pytest.approx(1.1)
    assert po_out["b"][3] == pytest.approx(0.9)


def test_registry_groups_labels_esd():
    """分组 / 标签 / e.s.d. 回填可用（P1.5 与 P3 导航依赖）。"""
    cfg = nl.RefineConfig(refine_zero=True, refine_uvw=True, refine_cell=True)
    reg: ParameterRegistry = build_registry_from_config(cfg, ProfileParams(), 1)
    assert reg.size == 1 + 3 + 2
    assert set(reg.groups()) == {"zero", "profile", "cell"}
    assert reg.labels()[0] == "global.zero"
    reg.set_esd(np.arange(reg.size, dtype=float) * 0.001)
    ps = reg.parameters()
    assert ps[0].esd == pytest.approx(0.0)
    assert ps[-1].esd == pytest.approx((reg.size - 1) * 0.001)
    assert all(p.histogram == "all" for p in ps)
    with pytest.raises(ValueError):
        reg.set_esd(np.zeros(2))
