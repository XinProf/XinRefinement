"""U-003 / B07：谱图读取重复 IO 收敛为单次读盘。

契约：
- legacy 文本路径（``.xy/.txt/.dat/.csv``）对同一路径只读盘 **1 次**；
- ``Pattern.meta`` 键集合与取值（含浮点）与改动前 golden **逐字不变**；
- ``detect_format`` 默认行为（不传 head/full_text）与旧实现一致；
- 未知扩展名异常文案逐字不变。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.vendor.text_formats import detect_format
from xinrefinement.core.vendor.text_formats import load_pattern as vendor_load_pattern

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "data" / "pattern_meta_golden.json"
XY_SAMPLE = ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy"

# pd 格式：loop_ + 2θ 列名 + 强度列名，其后两列数据
PD_DAT = (
    "loop_\n"
    "_pd_proc_2theta_corrected\n"
    "_pd_meas_intensity_total\n"
    "10.000 100.0\n"
    "10.020 110.0\n"
    "10.040 120.0\n"
)
# Jade/MDI：第 2 行必须是 start step mode anode wavelength stop npoints，
# 其后是单列定宽强度（本样本 10 个值）
JADE_TXT = (
    "Jade export\n"
    "5.0000 0.0200 0 CU 1.54060 90.0000 4251\n"
    "120 135 118 140 126 131 119 144 138 122\n"
)
# 岛津 ASCII：参数头 + `<2Theta> <Intensity>` 列名行 + 两列数据
SHIMADZU_TXT = (
    "Target : Cu\n"
    "Voltage : 40\n"
    "Current : 30\n"
    "Scan range : 10.000 - 20.000\n"
    "Sampling pitch : 0.020\n"
    "<2Theta> <Intensity>\n"
    "10.000 100.0\n"
    "10.020 110.0\n"
    "10.040 120.0\n"
)
# XRDML 最小样本：带编码声明，靠 start/end positions + 3 个强度展开成 3 点
XRDML_SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.5">\n'
    "  <sample><id>FIX3</id></sample>\n"
    "  <xrdMeasurement>\n"
    '    <scan appendNumber="0">\n'
    "      <dataPoints>\n"
    '        <positions axis="2Theta" unit="deg">\n'
    "          <startPosition>10.0</startPosition>\n"
    "          <endPosition>10.10</endPosition>\n"
    "        </positions>\n"
    '        <intensities unit="counts">100 110 120</intensities>\n'
    "      </dataPoints>\n"
    "      <datasource><xroadata><xraySource>Cu</xraySource></xroadata></datasource>\n"
    "    </scan>\n"
    "  </xrdMeasurement>\n"
    "</xrdMeasurements>\n"
)


def _sample_path(tmp_path: Path, name: str) -> Path:
    """按 golden 快照用的固定文件名落盘（path 归一成 basename 后才有可比性）。"""
    if name == "legacy_two_column":
        return XY_SAMPLE
    filename, content = {
        "pd_dat": ("pd_sample.dat", PD_DAT),
        "vendor_jade_txt": ("jade_sample.txt", JADE_TXT),
        "vendor_shimadzu_txt": ("shimadzu_sample.txt", SHIMADZU_TXT),
    }[name]
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8", newline="")
    return path


def _normalized_meta(meta: dict) -> dict:
    """绝对路径跨机器不可比：path / source_file 统一归一成文件名。"""
    out = dict(meta)
    out["path"] = Path(out["path"]).name
    if "source_file" in out:
        out["source_file"] = Path(out["source_file"]).name
    return out


def _count_disk_reads(monkeypatch: pytest.MonkeyPatch, target: Path) -> list[int]:
    """统计 ``target`` 被物理读盘的次数（read_bytes / read_text / open）。

    桩函数直连原 ``Path.open``，避免 read_bytes/read_text 内部再进一次 open
    被重复计数（一次读盘只记一次）。
    """
    calls = [0]
    target_key = target.resolve()
    orig_open = Path.open
    orig_read_bytes = Path.read_bytes
    orig_read_text = Path.read_text

    def hit(self) -> bool:
        return Path(self).resolve() == target_key

    def read_bytes(self):
        if hit(self):
            calls[0] += 1
        with orig_open(self, "rb") as fh:
            return fh.read()

    def read_text(self, encoding=None, errors=None):
        if hit(self):
            calls[0] += 1
        with orig_open(self, "r", encoding=encoding, errors=errors) as fh:
            return fh.read()

    def open_(self, *args, **kwargs):
        if hit(self):
            calls[0] += 1
        return orig_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "open", open_)
    return calls


@pytest.mark.parametrize("name", ["legacy_two_column"])
def test_single_disk_read_legacy_two_column(monkeypatch, tmp_path, name):
    path = _sample_path(tmp_path, name)
    calls = _count_disk_reads(monkeypatch, path)
    pattern = load_pattern(path)
    assert pattern.two_theta.size > 2
    assert calls[0] == 1


def test_single_disk_read_pd_dat(monkeypatch, tmp_path):
    path = _sample_path(tmp_path, "pd_dat")
    calls = _count_disk_reads(monkeypatch, path)
    pattern = load_pattern(path)
    assert pattern.meta["layout"] == "pd"
    assert calls[0] == 1


def test_single_disk_read_vendor_jade_txt(monkeypatch, tmp_path):
    path = _sample_path(tmp_path, "vendor_jade_txt")
    calls = _count_disk_reads(monkeypatch, path)
    pattern = load_pattern(path)
    assert pattern.meta["format_key"] == "jade_txt"
    assert calls[0] == 1


def test_single_disk_read_vendor_shimadzu_txt(monkeypatch, tmp_path):
    path = _sample_path(tmp_path, "vendor_shimadzu_txt")
    calls = _count_disk_reads(monkeypatch, path)
    pattern = load_pattern(path)
    assert pattern.meta["format_key"] == "shimadzu_txt"
    assert calls[0] == 1


def test_meta_matches_golden(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name, expected in golden.items():
        path = _sample_path(tmp_path, name)
        actual = _normalized_meta(load_pattern(path).meta)
        assert actual == expected, f"{name} 的 meta 与 golden 不一致"


def test_detect_format_default_behaviour_unchanged(tmp_path):
    cases = {
        "legacy_two_column": "xy",
        "pd_dat": "dat",
        "vendor_jade_txt": "jade_txt",
        "vendor_shimadzu_txt": "shimadzu_txt",
    }
    for name, expected_key in cases.items():
        path = _sample_path(tmp_path, name)
        default_key, default_label = detect_format(path)
        assert (default_key, default_label) == (expected_key, expected_key)
        # 传入已读字节的新路径必须与默认路径给出同一结论
        assert detect_format(path, head=path.read_bytes()) == (expected_key, expected_key)


def test_xrdml_fromstring_equals_parse(tmp_path):
    """``ET.fromstring(raw)`` 与 ``ET.parse(path)`` 两条路径必须给出同一谱图。

    前者吃字节（按 XML 声明解码），后者吃文件名（由 expat 自行嗅探编码），
    二者在 BOM / 编码声明上的处理可能不同，故逐元素对拍锁死等价性。
    """
    path = tmp_path / "sample.xrdml"
    raw = XRDML_SAMPLE.encode("utf-8")
    path.write_bytes(raw)

    with_raw = vendor_load_pattern(path, raw=raw, key="xrdml")
    without_raw = vendor_load_pattern(path, key="xrdml")

    assert with_raw.two_theta.size >= 2
    assert np.array_equal(with_raw.two_theta, without_raw.two_theta)
    assert np.array_equal(with_raw.intensity, without_raw.intensity)
    assert with_raw.metadata == without_raw.metadata


def test_unsupported_ext_message_unchanged(tmp_path):
    path = tmp_path / "sample.foo"
    path.write_text("1 2\n3 4\n", encoding="utf-8")
    with pytest.raises(NotImplementedError, match=r"^暂不支持的格式: \.foo$"):
        load_pattern(path)
