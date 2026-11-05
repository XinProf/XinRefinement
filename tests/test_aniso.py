"""v1.3 任务 #15：Popa LB 各向异性尺寸/应变（2 阶截断，Cholesky 参数化）。

模型：``1/D² = |L_sᵀn|²``、``ε² = |L_εᵀn|²``（n = 反射的笛卡尔单位法向），
``Y = (180/π)·Kλ/√(1/D²)``、``X = (180/π)·4ε``——与标量 TCH 同单位同语义。
可辨识性护栏：默认只放 ``size``（6 参）；窗口内独立晶向 < 8 直接报错。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.params.registry import build_registry_from_config
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import (
    ProfileParams,
    aniso_default,
    aniso_dirs,
    aniso_ratios,
    aniso_xy,
    compute_phase_profile,
)
from xinrefinement.core.refine.nonlinear import (
    RefineConfig,
    _bounds,
    _pack,
    _unpack,
)
from xinrefinement.core.refine.solve import RefineInputs, solve

DATA = Path(__file__).parent.parent / "xinrefinement" / "data"
VIRTUAL_B = Path(__file__).parent / "data" / "virtual_b"


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]


def test_isotropic_aniso_equals_scalar_x_y(structs):
    """各向同性系数与标量 X/Y 逐位等价（退化为 TCH 标量路径）。"""
    grid = np.linspace(10.0, 90.0, 6001)
    iso = aniso_default(1.5406, x_deg=0.12, y_deg=0.2)
    assert aniso_xy(iso, (0, 0, 1), 1.5406) == pytest.approx((0.12, 0.2), rel=1e-9)
    n111 = tuple(np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0))
    assert aniso_xy(iso, n111, 1.5406) == pytest.approx((0.12, 0.2), rel=1e-9)
    y_scalar = compute_phase_profile(
        structs[0], grid, ProfileParams(U=0.02, V=0.0, W=0.02, eta=0.5,
                                        anode="Cu", X=0.12, Y=0.2))
    y_aniso = compute_phase_profile(
        structs[0], grid, ProfileParams(U=0.02, V=0.0, W=0.02, eta=0.5,
                                        anode="Cu",
                                        aniso={structs[0].name: iso}))
    assert np.allclose(y_scalar, y_aniso, rtol=1e-9, atol=1e-6)


def test_aniso_direction_dependent_width(structs):
    """各向异性：c 向晶粒更小 -> (00l) 峰更宽、(hk0) 峰更窄。"""
    grid = np.linspace(10.0, 90.0, 12001)
    entry = {"size": [1 / 300.0, 0.0, 1 / 300.0, 0.0, 0.0, 1 / 40.0],
             "strain": [1e-6, 0.0, 1e-6, 0.0, 0.0, 1e-6]}
    prm = ProfileParams(U=0.0, V=0.0, W=0.005, eta=0.5, anode="Cu",
                        aniso={structs[0].name: entry})
    y_an = compute_phase_profile(structs[0], grid, prm)
    y_iso = compute_phase_profile(
        structs[0], grid,
        ProfileParams(U=0.0, V=0.0, W=0.005, eta=0.5, anode="Cu"))
    # 004 (2θ≈37.8°) 属于 c 向小晶粒 -> 明显展宽；101 (25.3°) 变化较小
    def _peak_width(y, center, half=1.5):
        m = (grid > center - half) & (grid < center + half)
        return float(np.sum(y[m]) / max(y[m].max(), 1e-30))
    w004_an, w004_iso = _peak_width(y_an, 37.8), _peak_width(y_iso, 37.8)
    assert w004_an > w004_iso * 1.5
    assert aniso_ratios(entry)[0] == pytest.approx(300.0 / 40.0, rel=1e-6)


def test_registry_matches_engine_both_modes(structs):
    """registry 与旧 _pack/_unpack/_bounds 在 size / both 两种模式下逐位一致。"""
    iso = aniso_default(1.5406, 0.05, 0.1)
    prm = ProfileParams(U=0.1, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        aniso={structs[0].name: iso})
    for mode, n in (("size", 6), ("both", 12)):
        cfg = RefineConfig(refine_zero=True, refine_aniso=True, aniso_mode=mode)
        reg = build_registry_from_config(cfg, prm, 1)
        assert np.array_equal(reg.pack(prm), _pack(prm, cfg, 1)), mode
        lo_r, hi_r = reg.bounds()
        lo_o, hi_o = _bounds(cfg, 1, 0, 0, 0, 1)
        assert np.array_equal(lo_r, lo_o) and np.array_equal(hi_r, hi_o), mode
        # zero(1) + U,V,W(3) + 各向异性系数(n)
        assert reg.size == 1 + 3 + n
        prm_r, _, _ = reg.unpack(reg.pack(prm), prm)
        prm_o, _ = _unpack(_pack(prm, cfg, 1), prm, cfg, 1)
        assert prm_r.aniso == prm_o.aniso, mode


def test_undetermined_dirs_raises(structs):
    """窗口内独立晶向 < 8 时显式报错（12/6 系数不可辨识）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    iso = aniso_default(1.5406)
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        aniso={structs[0].name: iso})
    cfg = RefineConfig(refine_aniso=True, n_bg=2, max_iter=5,
                       tmin=36.8, tmax=39.0)
    with pytest.raises(ValueError, match="欠定"):
        solve(RefineInputs(pattern=pat, phases=[structs[0]],
                           profile=prm, config=cfg))


def test_dirs_count(structs):
    """窗口内独立晶向数（anatase，5–90°）应远多于护栏阈值。"""
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    dirs = aniso_dirs(structs[0], prm, 5.0, 90.0)
    assert dirs.shape[0] >= 8


@pytest.fixture(scope="module")
def synthetic(structs):
    """合成各向异性尺寸数据：anatase a 向 D=200 Å、c 向 D=60 Å（比 3.33）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    base = solve(RefineInputs(
        pattern=pat, phases=structs,
        profile=ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu"),
        config=RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                            refine_size=True, refine_strain=True, n_bg=3,
                            max_iter=40, tmin=5.0, tmax=90.0)))
    prm_fit = base.params
    tt = base.pattern.two_theta
    sc0 = float(base.engine.scales[0])
    truth = {"size": [1 / 200.0, 0.0, 1 / 200.0, 0.0, 0.0, 1 / 60.0],
             "strain": [1e-6, 0.0, 1e-6, 0.0, 0.0, 1e-6]}
    prm_truth = replace(prm_fit, aniso={structs[0].name: truth}, X=0.0, Y=0.0)
    y0 = compute_phase_profile(structs[0], tt, prm_fit)
    y1 = compute_phase_profile(structs[0], tt, prm_truth)
    pat_syn = Pattern(two_theta=tt, intensity=base.ycalc - y0 * sc0 + y1 * sc0,
                      meta=dict(pat.meta))
    iso = aniso_default(prm_fit.wavelength, prm_fit.X, prm_fit.Y)
    return pat_syn, prm_fit, iso, truth


def test_recover_aniso_size(synthetic, structs):
    """各向同性拟合劣化 -> 各向异性（size）精修恢复并回收各向异性比。"""
    pat_syn, prm_fit, iso, truth = synthetic
    cfg = RefineConfig(n_bg=3, max_iter=20, tmin=5.0, tmax=90.0)
    bad = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_fit, config=cfg))
    assert bad.rwp > 20.0

    prm_an = replace(prm_fit, aniso={structs[0].name: iso})
    cfg_an = RefineConfig(refine_aniso=True, aniso_mode="size", n_bg=3,
                          max_iter=40, tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_an, config=cfg_an))
    assert got.success
    assert got.rwp < 1.0                      # 合成谱无噪 -> 应几乎完美
    entry = got.params.aniso[structs[0].name]
    # Cholesky 对角 = 各方向的 1/D（沿 c 的 l33、沿 a 的 l11）
    assert entry["size"][0] == pytest.approx(truth["size"][0], rel=0.10)
    assert entry["size"][5] == pytest.approx(truth["size"][5], rel=0.10)
    d_ratio, _e_ratio = aniso_ratios(entry)
    assert d_ratio == pytest.approx(200.0 / 60.0, rel=0.10)
    assert any("Popa LB" in w for w in got.warnings)


def test_both_mode_warns(synthetic, structs):
    """both 模式给出「互相吸收」风险告警。"""
    pat_syn, prm_fit, iso, _truth = synthetic
    prm_an = replace(prm_fit, aniso={structs[0].name: iso})
    cfg = RefineConfig(refine_aniso=True, aniso_mode="both", n_bg=3,
                       max_iter=6, tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_an, config=cfg))
    assert any("互相吸收" in w for w in got.warnings)


def test_cli_aniso_roundtrip(tmp_path):
    """CLI --aniso 端到端：报告带 size/strain 系数。"""
    import json

    from tests.test_cli import _common
    from xinrefinement.cli.refine import main

    out = tmp_path / "aniso.json"
    argv = _common(tmp_path, "aniso.json") + [
        "--aniso", "anatase=size", "--max-iter", "6"]
    assert main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    an = data["parameters"]["aniso"]["anatase"]
    assert len(an["size"]) == 6 and len(an["strain"]) == 6
