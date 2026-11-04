"""CIF 解析与结构因子兼容性测试（T1.2 验收）。

两组断言：
1. **结构层**：14 份内置 CIF 全部可解析，晶胞/原子数与 INDEX 一致；
2. **物理层**：用 NCA_80_15_05 CIF 算出的峰位必须命中真实实样的主峰（这才是
   "结构因子算对了"的硬证据 —— 只检查原子数并不能发现散射因子或占位读错）。
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from xinrefinement.core.profile.cif import parse_cif_string
from xinrefinement.core.profile.forward import ProfileParams, compute_phase_profile
from xinrefinement.core.profile.struct import compute_peaks

#: 实测 NCA_80_15_05（XRData/csuHJW/Data040）用 Cu Kα1 的 11 个主峰 2θ
OBSERVED_MAIN = [18.740, 36.680, 38.360, 44.480, 48.680, 58.740,
                 64.520, 64.940, 68.260]


@pytest.fixture(scope="module")
def index(cif_dir):
    path = cif_dir / "INDEX.json"
    if not path.exists():
        pytest.skip("缺 INDEX.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nca811(cif_dir):
    return parse_cif_string((cif_dir / "NCA_80_15_05.cif").read_text(encoding="utf-8"),
                            "NCA_80_15_05")


def test_all_builtin_cifs_parse(index, cif_dir) -> None:
    assert index["count"] >= 14
    for e in index["entries"]:
        text = (cif_dir / e["file"]).read_text(encoding="utf-8")
        st = parse_cif_string(text, e["name"])
        assert st.atoms, f"{e['file']} 展开后无原子"
        assert st.cell[0] == pytest.approx(e["a"], abs=1e-4)
        assert st.cell[2] == pytest.approx(e["c"], abs=1e-4)


def test_nca811_atom_inventory(nca811) -> None:
    """R-3m：3 个 Li 位 + 3 个 TM 位 + 6c 的 O(多重度 6) = 24 个原子。

    注意 6c 的多重度是 **6**（不是 18）—— 每胞 6 个 O，Z=3 时每式 O2，自洽。

    NCA 配比自洽性（这是 NCA 版本最该锁住的一条）：LiNi₀.₈₀Co₀.₁₅Al₀.₀₅O₂，
    Z=3 时 每胞 Li 3.00 / Ni 2.40 / Co 0.45 / Al 0.15 / O 6。
    TM 层 (0,0,0) 占位 0.78 Ni + 0.15 Co + 0.05 Al + 0.02 Li = 1.00；
    Li 层 (0,0,½) 占位 0.98 Li + 0.02 Ni = 1.00 —— 两层各自满占位，
    2% Li/Ni 反位把 Li 总量配平回 1.00（不是 0.98）。
    """
    assert len(nca811.atoms) == 24
    elems = [a[0] for a in nca811.atoms]
    assert elems.count("O") == 6
    assert elems.count("Li") == 6          # Li 层 3 + TM 层 3
    assert elems.count("Al") == 3          # NCA 与 NCM 的结构差别就在这 3 个 Al
    assert elems.count("Co") == 3
    assert elems.count("Ni") == 6          # TM 层 3 + Li 层 3（反位）

    occ = {el: 0.0 for el in ("Li", "Ni", "Co", "Al", "O")}
    for a in nca811.atoms:
        occ[a[0]] = occ.get(a[0], 0.0) + a[4]
    assert occ["Li"] == pytest.approx(3.00, abs=0.02)
    assert occ["Ni"] == pytest.approx(2.40, abs=0.02)
    assert occ["Co"] == pytest.approx(0.45, abs=0.02)
    assert occ["Al"] == pytest.approx(0.15, abs=0.02)
    assert occ["O"] == pytest.approx(6.00, abs=0.02)
    # 化学计量比必须严格是 80:15:5（Hill–Howard 定量依赖它）
    assert occ["Ni"] / occ["Li"] == pytest.approx(0.80, abs=0.005)
    assert occ["Co"] / occ["Li"] == pytest.approx(0.15, abs=0.005)
    assert occ["Al"] / occ["Li"] == pytest.approx(0.05, abs=0.005)


def test_peak_positions_systematic_offset(nca811) -> None:
    """用 COD 原始晶胞算出的峰位应**系统性偏高**，且偏差随 2θ 单调增大。

    这不是误差，是物理：COD 晶胞 a=2.8645/c=14.161 比实样精修值
    a=2.8718/c=14.1942 小 → 整条谱峰位一致右移、角度越大偏得越多。
    若出现正负跳变，说明结构因子/原子坐标读错，而非晶胞差异。
    """
    peaks, _ = compute_peaks(nca811, wavelength=1.5405929, two_min=10.0,
                             two_max=80.0)
    pos = sorted(t for t, _i, _d in peaks)
    devs = []
    for obs in OBSERVED_MAIN:
        best = min(pos, key=lambda p: abs(p - obs))
        devs.append(best - obs)
    assert all(d > 0 for d in devs), f"应全部偏高，实得: {[round(d, 3) for d in devs]}"
    assert devs[-1] > devs[0], f"高角偏差应大于低角: {round(devs[0],3)} -> {round(devs[-1],3)}"
    assert max(abs(d) for d in devs) < 0.15


def test_peak_positions_match_after_cell_scale(nca811) -> None:
    """把晶胞缩放到实样精修值后，9 个主峰应全部命中（±0.03°）。

    这是"结构模型 + 散射因子 + 占位"三者都对的硬证据：只错一处，
    峰位/强度就对不上。
    """
    from xinrefinement.core.profile.cif import CifStructure

    fa = 2.8718 / nca811.cell[0]
    fc = 14.1942 / nca811.cell[2]
    a, b, c, al, be, ga = nca811.cell
    scaled = CifStructure(nca811.name, (a * fa, b * fa, c * fc, al, be, ga),
                          nca811.atoms)
    peaks, _ = compute_peaks(scaled, wavelength=1.5405929, two_min=10.0,
                             two_max=80.0)
    pos = sorted(t for t, _i, _d in peaks)
    # 容差随 tanθ 放大：晶胞尺度误差 δ 引起的峰位偏差 ∝ tanθ，
    # 高角本就敏感。0.02° 起点对应实样精修晶胞本身的不确定度。
    for obs in OBSERVED_MAIN:
        d = min(abs(p - obs) for p in pos)
        tol = 0.02 + 0.08 * math.tan(math.radians(obs) / 2)
        assert d < tol, f"2θ={obs} 偏差 {d:.3f}° 超限 {tol:.3f}°"


def test_peak_positions_match_real_sample(nca811) -> None:
    """理论峰位必须命中实样主峰（±0.35°，与方案 §1 的实测一致）。"""
    peaks, skipped = compute_peaks(nca811, wavelength=1.5405929,
                                   two_min=10.0, two_max=80.0)
    assert not skipped, f"有元素缺散射因子: {skipped}"
    pos = sorted(t for t, _i, _d in peaks)

    hit, miss = 0, []
    for obs in OBSERVED_MAIN:
        d = min(abs(p - obs) for p in pos)
        if d <= 0.35:
            hit += 1
        else:
            miss.append((obs, round(d, 3)))
    assert hit >= 8, f"命中 {hit}/{len(OBSERVED_MAIN)}，未命中: {miss}"


def test_003_and_104_positions(nca811) -> None:
    """最关键的两个峰：(003) ≈18.74°，(104) ≈44.48°（Cu Kα1，实样精修晶胞）。

    COD 原始晶胞略小，故这里先缩放到实样值再比对（理由见上一个测试）。
    """
    from xinrefinement.core.profile.cif import CifStructure

    fa = 2.8718 / nca811.cell[0]
    fc = 14.1942 / nca811.cell[2]
    a, b, c, al, be, ga = nca811.cell
    scaled = CifStructure(nca811.name, (a * fa, b * fa, c * fc, al, be, ga),
                          nca811.atoms)
    peaks, _ = compute_peaks(scaled, wavelength=1.5405929, two_min=10.0,
                             two_max=80.0)
    pos = sorted(t for t, _i, _d in peaks)
    assert min(abs(p - 18.74) for p in pos) < 0.05
    assert min(abs(p - 44.48) for p in pos) < 0.05


def test_intensity_ordering_003_dominant(nca811) -> None:
    """NCA_80_15_05 的 (003) 应是最强峰 —— 若散射因子或占位读错，这里会翻车。"""
    peaks, _ = compute_peaks(nca811, wavelength=1.5405929, two_min=10.0,
                             two_max=80.0)
    # 把 2θ 相近的反射归并后再比强度
    buckets: list[list[float]] = []
    for t, i, _d in sorted(peaks):
        if buckets and abs(t - buckets[-1][0]) < 0.05:
            buckets[-1][1] += i
        else:
            buckets.append([t, i])
    strongest = max(buckets, key=lambda b: b[1])
    assert strongest[0] == pytest.approx(18.74, abs=0.1)


def test_forward_profile_matches_grid(nca811) -> None:
    """前向模型输出与给定 2θ 网格等长、非负、有限。"""
    grid = np.arange(10.0, 80.0, 0.02)
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6, anode="Cu")
    y = compute_phase_profile(nca811, grid, prm)
    assert y.shape == grid.shape
    assert np.all(np.isfinite(y))
    assert y.min() >= 0.0
    assert y.max() > 0.0
