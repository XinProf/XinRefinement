"""v1.3 任务 #14：EWIMV 离散 ODF 织构（A1–A6 验收）。

模型：Bragg–Brentano 平板对称反射几何下，织构因子退化为每反射常数
``T(χ_hkl)``（χ = 晶面法向与织构轴夹角，0–90°）。每相一个 19 点网格
（5° 步长），二阶差分光滑罚 + 末端锚定 1.0 作正则化。
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
    TEXTURE_N_GRID,
    ProfileParams,
    compute_phase_profile,
    default_texture_grid,
    normalize_texture_grid,
    texture_chi,
    texture_chi_buckets,
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
AXIS = (0, 0, 1)


@pytest.fixture(scope="module")
def structs():
    return [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]


@pytest.fixture(scope="module")
def synthetic(structs):
    """带人造织构（anatase (001) 方向 T=3）的无噪合成谱 + 基线参数。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    cfg0 = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                        refine_size=True, refine_strain=True, n_bg=3,
                        max_iter=40, tmin=5.0, tmax=90.0)
    base = solve(RefineInputs(
        pattern=pat, phases=structs, config=cfg0,
        profile=ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")))
    prm_fit = base.params
    tt = base.pattern.two_theta
    scale0 = float(base.engine.scales[0])
    truth = [3.0] + [1.0] * (TEXTURE_N_GRID - 1)
    y0 = compute_phase_profile(structs[0], tt, prm_fit)
    y1 = compute_phase_profile(
        structs[0], tt,
        replace(prm_fit, texture={structs[0].name: {"axis": AXIS,
                                                    "grid": truth}}))
    y_syn = base.ycalc - y0 * scale0 + y1 * scale0
    pat_syn = Pattern(two_theta=tt, intensity=y_syn, meta=dict(pat.meta))
    return pat_syn, prm_fit, truth


def test_a1_no_texture_bitwise_unchanged(structs):
    """A1：texture=None 时前向模型与未加该功能前逐位一致。"""
    grid = np.linspace(10.0, 90.0, 3001)
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    y = compute_phase_profile(structs[0], grid, prm)
    # 追加全 1 网格（等价无织构）应逐位相同
    y1 = compute_phase_profile(
        structs[0], grid,
        replace(prm, texture={structs[0].name: {"axis": AXIS,
                                                "grid": default_texture_grid()}}))
    assert np.allclose(y, y1, rtol=0.0, atol=1e-9)


def test_a1_registry_pack_matches_engine(structs):
    """A1：registry 与旧 _pack/_unpack/_bounds 在织构槽位上逐位一致。"""
    prm = ProfileParams(U=0.1, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        texture={structs[0].name: {"axis": AXIS,
                                                   "grid": default_texture_grid()}})
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_size=True,
                       refine_texture=True)
    reg = build_registry_from_config(cfg, prm, 2)
    assert np.array_equal(reg.pack(prm), _pack(prm, cfg, 2))
    lo_r, hi_r = reg.bounds()
    lo_o, hi_o = _bounds(cfg, 2, 0, 0, TEXTURE_N_GRID)
    assert np.array_equal(lo_r, lo_o) and np.array_equal(hi_r, hi_o)
    prm_r, _, _ = reg.unpack(reg.pack(prm), prm)
    prm_o, _ = _unpack(_pack(prm, cfg, 2), prm, cfg, 2)
    assert prm_r.texture == prm_o.texture
    assert prm_r.Y == prm_o.Y


def test_a2_a3_recover_texture(synthetic, structs):
    """A2/A3：无织构拟合 Rwp 明显恶化，开织构后恢复且 T(0)≈3。"""
    pat_syn, prm_fit, truth = synthetic
    cfg = RefineConfig(n_bg=3, max_iter=20, tmin=5.0, tmax=90.0)
    bad = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_fit, config=cfg))
    assert bad.rwp > 5.0                     # 无织构模型拟合不了人造织构

    prm_tex = replace(prm_fit, texture={
        structs[0].name: {"axis": AXIS, "grid": default_texture_grid()}})
    cfg_tex = RefineConfig(refine_texture=True, n_bg=3, max_iter=40,
                           tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_tex, config=cfg_tex))
    assert got.success
    assert got.rwp < 0.5                     # 合成谱无噪声 -> 应几乎完美
    grid = np.asarray(got.params.texture[structs[0].name]["grid"])
    # T(χ=0) 直接由 (00l) 反射约束 -> 精确回收
    assert grid[0] == pytest.approx(truth[0], rel=0.15)
    # 末端锚定保持 1.0（远场无织构）
    assert grid[-1] == pytest.approx(1.0, abs=0.05)
    # 未覆盖的中间节点由光滑罚过渡，不触界
    assert np.all(grid > 0.5) and np.all(grid < 4.0)


def test_a4_undetermined_raises(structs):
    """A4：相内独立 χ 桶 < 3 时显式报错（不静默给结果）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu",
                        texture={structs[0].name: {"axis": AXIS,
                                                   "grid": default_texture_grid()}})
    cfg = RefineConfig(refine_texture=True, n_bg=2, max_iter=5,
                       tmin=37.2, tmax=38.4)   # 只剩 (004) 一个 χ=0 反射
    with pytest.raises(ValueError, match="欠定"):
        solve(RefineInputs(pattern=pat, phases=[structs[0]],
                           profile=prm, config=cfg))


def test_a4_lambda_zero_still_runs(synthetic, structs):
    """A4：λ=0（关正则化）仍可跑；结果由数据约束（不炸/不 NaN）。"""
    pat_syn, prm_fit, _truth = synthetic
    prm_tex = replace(prm_fit, texture={
        structs[0].name: {"axis": AXIS, "grid": default_texture_grid()}})
    cfg = RefineConfig(refine_texture=True, texture_lambda=0.0, n_bg=3,
                       max_iter=10, tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm_tex, config=cfg))
    grid = np.asarray(got.params.texture[structs[0].name]["grid"])
    assert np.all(np.isfinite(grid))
    assert np.all(grid >= 0.1 - 1e-9) and np.all(grid <= 10.0 + 1e-9)


def test_a5_march_dollase_mutually_exclusive(synthetic, structs):
    """A5：开织构的相忽略 po_r 并给出 warning。"""
    pat_syn, prm_fit, _truth = synthetic
    prm = replace(prm_fit,
                  po_r={structs[0].name: (0, 0, 1, 1.4)},
                  texture={structs[0].name: {"axis": AXIS,
                                             "grid": default_texture_grid()}})
    cfg = RefineConfig(refine_texture=True, n_bg=3, max_iter=8,
                       tmin=5.0, tmax=90.0)
    got = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm, config=cfg))
    assert any("March–Dollase" in w and "忽略" in w for w in got.warnings)


def test_a6_esd_finite(synthetic, structs):
    """A6：e.s.d. 走 registry 自动覆盖，织构列给出有限正值。"""
    from xinrefinement.core.refine.esd import estimate_esd

    pat_syn, prm_fit, _truth = synthetic
    prm = replace(prm_fit, texture={
        structs[0].name: {"axis": AXIS, "grid": default_texture_grid()}})
    cfg = RefineConfig(refine_texture=True, n_bg=3, max_iter=8,
                       tmin=5.0, tmax=90.0)
    res = solve(RefineInputs(pattern=pat_syn, phases=structs,
                             profile=prm, config=cfg))
    out = estimate_esd(structs, res)
    labels = list(out.labels)
    tex_idx = [i for i, k in enumerate(labels) if ".texture." in k]
    assert tex_idx, "e.s.d. 未覆盖织构参数"
    vals = np.asarray(out.esd, dtype=float)
    assert np.all(np.isfinite(vals[tex_idx]))
    assert np.all(vals[tex_idx] >= 0.0)


def test_texture_chi_geometry(structs):
    """χ 几何：同轴 0°、垂直 90°、anatase (101) 与 (001) 夹角 ≈68.3°。"""
    st = structs[0]
    assert texture_chi((0, 0, 1), AXIS, st.cell) == pytest.approx(0.0, abs=1e-9)
    assert texture_chi((1, 0, 0), AXIS, st.cell) == pytest.approx(90.0, abs=1e-6)
    assert texture_chi((1, 0, 1), AXIS, st.cell) == pytest.approx(68.32, abs=0.1)
    n_buckets, chis = texture_chi_buckets(st, ProfileParams(
        U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu"), AXIS, 5.0, 90.0)
    assert n_buckets >= 3 and chis.size > 0
    assert chis.min() >= -1e-9 and chis.max() <= 90.0 + 1e-6


def test_normalize_grid_resamples():
    """任意长度网格线性重采样到 19 点；空输入给全 1。"""
    assert len(normalize_texture_grid([2.0])) == TEXTURE_N_GRID
    assert normalize_texture_grid(None) == [1.0] * TEXTURE_N_GRID
    got = normalize_texture_grid([3.0, 1.0])
    assert got[0] == pytest.approx(3.0) and got[-1] == pytest.approx(1.0)


def test_cli_texture_roundtrip(tmp_path):
    """CLI --texture 端到端：精修后报告里带 19 点 T(χ) 网格。"""
    import json

    from xinrefinement.cli.refine import main
    from tests.test_cli import _common

    out = tmp_path / "tex.json"
    argv = _common(tmp_path, "tex.json") + [
        "--texture", "anatase=0,0,1", "--max-iter", "8"]
    assert main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    tex = data["parameters"]["texture"]
    assert "anatase" in tex
    assert tex["anatase"]["axis"] == [0, 0, 1]
    assert len(tex["anatase"]["grid"]) == TEXTURE_N_GRID
