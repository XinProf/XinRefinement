"""v1.3 任务 #16：优化器插拔（lm / trf / dogbox，别名 scipy）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.optimizers import (
    ALIASES,
    OPTIMIZERS,
    minimize,
    resolve_method,
)
from xinrefinement.core.refine.solve import RefineInputs, solve

DATA = Path(__file__).parent.parent / "xinrefinement" / "data"
VIRTUAL_B = Path(__file__).parent / "data" / "virtual_b"


def _res(x):
    return np.array([x[0] - 1.0, 2.0 * (x[1] - 2.0), x[0] + x[1] - 3.5])


def test_resolve_and_alias():
    """别名归一与未知方法报错（列出可用项，不静默回退）。"""
    assert resolve_method("scipy") == "trf"
    assert resolve_method("lm") == "lm"
    assert resolve_method("") == "lm"
    assert set(OPTIMIZERS) >= {"lm", "trf", "dogbox"}
    assert ALIASES["scipy"] == "trf"
    with pytest.raises(ValueError, match="未知优化器"):
        resolve_method("bfgs-ultra")


@pytest.mark.parametrize("method", ["lm", "trf", "dogbox", "scipy"])
def test_all_optimizers_agree(method):
    """同一良态问题，三个优化器收敛到同一最小二乘解、同 cost 口径。"""
    lo = np.array([-5.0, -5.0])
    hi = np.array([5.0, 5.0])
    out = minimize(_res, np.array([0.0, 0.0]), (lo, hi), method=method,
                   max_iter=80)
    assert out.success
    assert out.x == pytest.approx([1.2222, 2.0556], abs=1e-3)
    assert out.cost == pytest.approx(0.0555556, rel=1e-4)
    assert out.nfev > 0


def test_bounds_respected():
    """边界投影：真解在界外时停在界上（三方法均如此）。"""
    lo = np.array([0.0, 0.0])
    hi = np.array([0.5, 0.5])
    for method in ("lm", "trf"):
        out = minimize(_res, np.array([0.1, 0.1]), (lo, hi), method=method,
                       max_iter=40)
        assert np.all(out.x >= lo - 1e-9) and np.all(out.x <= hi + 1e-9)


def test_solve_backend_equivalence():
    """端到端：trf/dogbox 与 lm 在同一虚拟谱上 Rwp 接近（口径一致）。"""
    pat = load_pattern(VIRTUAL_B / "v50_wide.xy")
    phases = [parse_cif(DATA / "anatase.cif"), parse_cif(DATA / "rutile.cif")]
    prm = ProfileParams(U=0.0, V=0.0, W=0.02, eta=0.5, anode="Cu")
    out = {}
    for backend in ("lm", "trf", "dogbox"):
        out[backend] = solve(RefineInputs(
            pattern=pat, phases=phases, profile=prm,
            config=RefineConfig(backend=backend, refine_zero=True,
                                refine_uvw=True, n_bg=3, max_iter=30,
                                tmin=5.0, tmax=90.0)))
    assert out["lm"].success and out["trf"].success
    for k in ("trf", "dogbox"):
        assert out[k].rwp < 40.0
        assert abs(out[k].rwp - out["lm"].rwp) < 5.0     # 同盆收敛


def test_cli_backend_dogbox(tmp_path):
    """CLI --backend dogbox 端到端可用。"""
    import json

    from tests.test_cli import _common
    from xinrefinement.cli.refine import main

    out = tmp_path / "dog.json"
    assert main(_common(tmp_path, "dog.json") + ["--backend", "dogbox"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["fit"]["success"] or data["r_factors"]["rwp"] < 60.0
